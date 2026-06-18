"""
💺 색상 기반 좌석 찾기 모듈

스크린샷 → 픽셀 색상 분석 → 지정된 색상과 일치하는 좌표 반환.
예전 매크로의 "좌석 색깔 검색" 방식을 그대로 구현.
"""
import io
import logging
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger("ticketlink_bot")


def find_seats_by_color(
    screenshot_bytes: bytes,
    target_bgr_hex: str,
    tolerance: int = 20,
    area: Optional[tuple[int, int, int, int]] = None,
    min_cluster_size: int = 5,
    max_results: int = 10,
) -> list[tuple[int, int]]:
    """
    스크린샷에서 지정된 색상과 일치하는 픽셀을 찾아 좌석 좌표 반환.

    Args:
        screenshot_bytes: CDP Page.captureScreenshot PNG 바이트
        target_bgr_hex: 타겟 색상 (BGR hex, e.g. 'C8C8C8' = 회색)
        tolerance: 색상 오차범위 (0~255, 클수록 넓게 탐색)
        area: 탐색 영역 (x1, y1, x2, y2) — None이면 전체 화면
        min_cluster_size: 최소 클러스터 크기 (작을수록 민감)
        max_results: 최대 반환 좌표 수

    Returns:
        [(x, y), ...] — 빈 좌석으로 추정되는 좌표 리스트 (viewport 기준)
    """
    img = Image.open(io.BytesIO(screenshot_bytes))
    w, h = img.size
    pixels = np.array(img.convert("RGB"))

    # BGR hex → RGB
    target_rgb = (
        int(target_bgr_hex[4:6], 16),  # R
        int(target_bgr_hex[2:4], 16),  # G
        int(target_bgr_hex[0:2], 16),  # B
    )

    # 영역 crop
    if area:
        ax1, ay1, ax2, ay2 = area
        ax1 = max(0, min(ax1, w))
        ax2 = max(0, min(ax2, w))
        ay1 = max(0, min(ay1, h))
        ay2 = max(0, min(ay2, h))
        pixels = pixels[ay1:ay2, ax1:ax2]
    else:
        ax1, ay1 = 0, 0

    # 색상 범위
    lower = np.array([
        max(0, target_rgb[0] - tolerance),
        max(0, target_rgb[1] - tolerance),
        max(0, target_rgb[2] - tolerance),
    ], dtype=np.uint8)
    upper = np.array([
        min(255, target_rgb[0] + tolerance),
        min(255, target_rgb[1] + tolerance),
        min(255, target_rgb[2] + tolerance),
    ], dtype=np.uint8)

    # 마스크 생성
    mask = np.all((pixels >= lower) & (pixels <= upper), axis=-1)
    matches = np.argwhere(mask)

    if len(matches) == 0:
        logger.info("  🔍 일치하는 색상 없음")
        return []

    logger.info("  🔍 일치 픽셀: %d개", len(matches))

    # 좌표 변환 (crop 보정)
    coords = [(int(x) + ax1, int(y) + ay1) for y, x in matches]

    # 클러스터링: 가까운 좌표끼리 묶기
    clusters = _cluster_points(coords, distance_threshold=15)

    # 클러스터 필터링 (최소 크기 이상만)
    valid_clusters = [c for c in clusters if len(c) >= min_cluster_size]

    if not valid_clusters:
        logger.info("  🔍 클러스터 조건 불충분 (최소 %dpx)", min_cluster_size)
        return []

    # 각 클러스터의 중심 좌표 계산, 크기순 정렬
    results = []
    for cluster in valid_clusters:
        cx = sum(p[0] for p in cluster) // len(cluster)
        cy = sum(p[1] for p in cluster) // len(cluster)
        results.append(((cx, cy), len(cluster)))

    results.sort(key=lambda x: -x[1])  # 큰 클러스터 우선

    logger.info("  🎯 후보 좌석: %d개", len(results[:max_results]))
    for (cx, cy), size in results[:max_results]:
        logger.info("     (%d, %d) — %dpx", cx, cy, size)

    return [pos for pos, _ in results[:max_results]]


def pick_color_at(
    screenshot_bytes: bytes,
    x: int,
    y: int,
) -> str:
    """지정 좌표의 색상을 BGR hex로 반환 (좌석 색상 설정용)"""
    img = Image.open(io.BytesIO(screenshot_bytes))
    pixels = np.array(img.convert("RGB"))
    h, w = pixels.shape[:2]

    if x < 0 or x >= w or y < 0 or y >= h:
        raise ValueError(f"좌표 ({x}, {y})가 이미지 범위를 벗어남 ({w}x{h})")

    r, g, b = int(pixels[y, x][0]), int(pixels[y, x][1]), int(pixels[y, x][2])
    # BGR hex (매크로 호환 형식)
    return f"{b:02X}{g:02X}{r:02X}"


def _cluster_points(
    points: list[tuple[int, int]],
    distance_threshold: int = 15,
) -> list[list[tuple[int, int]]]:
    """유클리드 거리 기반 단순 클러스터링"""
    if not points:
        return []

    clusters = [[points[0]]]
    for pt in points[1:]:
        added = False
        for cluster in clusters:
            cx = sum(p[0] for p in cluster) // len(cluster)
            cy = sum(p[1] for p in cluster) // len(cluster)
            dist = ((pt[0] - cx) ** 2 + (pt[1] - cy) ** 2) ** 0.5
            if dist <= distance_threshold:
                cluster.append(pt)
                added = True
                break
        if not added:
            clusters.append([pt])

    return clusters


def find_seats_in_zones(
    screenshot_bytes: bytes,
    zones: list[dict],
    max_results_per_zone: int = 10,
) -> dict[str, list[tuple[int, int]]]:
    """
    여러 구역(zone)에서 좌석 검색. 통합매크로 방식.

    Args:
        screenshot_bytes: CDP Page.captureScreenshot PNG 바이트
        zones: [
            {"area": [x1,y1,x2,y2], "color": "C8C8C8", "tolerance": 20},
            ...
        ]
        max_results_per_zone: 구역당 최대 좌석 수

    Returns:
        {"zones": [[(x,y), ...], ...], "all": [(x,y), ...]}
        - zones[i]: i번째 zone에서 찾은 좌석들
        - all: 모든 zone에서 찾은 좌석 통합 (중복 제거)
    """
    all_seats = []
    zone_results = []

    for zi, zone in enumerate(zones):
        area = tuple(zone.get("area", [0, 0, 0, 0]))
        color = zone.get("color", "C8C8C8")
        tol = zone.get("tolerance", 20)
        area_tuple = area if any(area) else None

        logger.info("  🔍 Zone %d: 색상=%s 오차=%d 영역=%s", zi + 1, color, tol, area)

        zone_seats = find_seats_by_color(
            screenshot_bytes, color, tolerance=tol,
            area=area_tuple, max_results=max_results_per_zone,
        )
        zone_results.append(zone_seats)

        # 중복 제거하며 통합
        existing = set(all_seats)
        for s in zone_seats:
            if s not in existing:
                all_seats.append(s)
                existing.add(s)

        logger.info("  ✅ Zone %d: %d석 발견 (누적 %d석)", zi + 1, len(zone_seats), len(all_seats))

    return {"zones": zone_results, "all": all_seats}


def find_consecutive_seats(
    seats: list[tuple[int, int]],
    n: int = 2,
    row_tolerance: int = 30,
    gap_tolerance: int = 40,
) -> list[tuple[int, int]]:
    """
    빈 좌석 목록에서 **N연석** (연속된 N개 좌석) 찾기.

    Args:
        seats: find_seats_by_color() 결과 [(x, y), ...]
        n: 몇 연석? (2=2연석, 3=3연석...)
        row_tolerance: 같은 행 판단 y축 오차 (px)
        gap_tolerance: 좌석 간격 최대 (px) — 이 이상 떨어지면 연속 아님

    Returns:
        연석 그룹 [(x1,y1), (x2,y2), ...] 또는 빈 리스트
    """
    if len(seats) < n:
        logger.info("  🔍 빈 좌석 부족: %d개 < %d연석", len(seats), n)
        return []

    # y 기준 행 그룹화
    rows: dict[int, list[tuple[int, int]]] = {}
    for sx, sy in seats:
        # 가까운 y 값 찾기
        matched = False
        for ry in rows:
            if abs(sy - ry) <= row_tolerance:
                rows[ry].append((sx, sy))
                matched = True
                break
        if not matched:
            rows[sy] = [(sx, sy)]

    # 각 행에서 x 정렬 후 연속 좌석 찾기
    best_group: list[tuple[int, int]] = []

    for ry, row_seats in rows.items():
        row_seats.sort(key=lambda p: p[0])  # x 정렬

        # 연속 그룹 찾기
        current_group = [row_seats[0]]
        for i in range(1, len(row_seats)):
            prev_x = current_group[-1][0]
            curr_x = row_seats[i][0]

            if (curr_x - prev_x) <= gap_tolerance:
                current_group.append(row_seats[i])
                if len(current_group) >= n:
                    # N연석 발견
                    group = current_group[-n:]  # 가장 최근 N개
                    if len(group) > len(best_group):
                        best_group = group
            else:
                current_group = [row_seats[i]]

    if best_group:
        logger.info("  🎯 %d연석 발견! (행 y≈%d)", n, best_group[0][1])
        for sx, sy in best_group:
            logger.info("     (%d, %d)", sx, sy)
        return best_group

    logger.info("  🔍 %d연석 못 찾음 (최대 %d개 그룹)", n, len(best_group))
    return []
