"""
💺 색상 기반 좌석 찾기 모듈

스크린샷 → 픽셀 색상 분석 → 지정된 색상과 일치하는 좌표 반환.
예전 매크로의 "좌석 색깔 검색" 방식을 그대로 구현.
"""
import io
import logging
import statistics
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
        screenshot_bytes: 시스템 스크린샷 PNG 바이트
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
        if ax1 > ax2: ax1, ax2 = ax2, ax1
        if ay1 > ay2: ay1, ay2 = ay2, ay1
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
        screenshot_bytes: 시스템 스크린샷 PNG 바이트
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
    existing = set()  # 중복 제거용 — loop 밖에서 한 번만 생성

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

        # 설정된 색상으로 2개 미만이면 → 자동 색상 감지 fallback
        if len(zone_seats) < 2:
            auto_color = _auto_detect_seat_color(
                screenshot_bytes, area=area_tuple, tolerance=30,
            )
            if auto_color and auto_color.upper() != color.upper():
                logger.info(
                    "  🔄 자동 감지 색상 %s 로 재시도 (기존 %s → %d석 부족)",
                    auto_color, color, len(zone_seats),
                )
                zone_seats = find_seats_by_color(
                    screenshot_bytes, auto_color, tolerance=tol,
                    area=area_tuple, max_results=max_results_per_zone,
                )

        zone_results.append(zone_seats)

        # 중복 제거하며 통합 (existing은 loop 밖에서 한 번 생성)
        for s in zone_seats:
            if s not in existing:
                all_seats.append(s)
                existing.add(s)

        logger.info("  ✅ Zone %d: %d석 발견 (누적 %d석)", zi + 1, len(zone_seats), len(all_seats))

    return {"zones": zone_results, "all": all_seats}


def _calc_adaptive_tolerances(
    seats: list[tuple[int, int]],
    fallback_row: int = 12,
    fallback_gap: int = 25,
) -> tuple[int, int]:
    """자동으로 좌석 좌표에서 row_tolerance와 gap_tolerance 계산.

    좌석들의 실제 배치 간격을 분석하여 적응형 임계값을 반환.
    데이터가 부족하면 fallback 값을 사용한다.

    행 임계값 계산 방식 (v0.9.29 개선):
      - y정렬 후 최대 y-gap = 행 간격으로 추정
      - 행 임계값 = 추정 행간 × 0.6 (≥10px)
      - 하드코딩된 15px → 데이터 기반 자동 계산으로 변경
        (행 내 y변동이 큰 좌석맵에서도 안정적 그룹화)

    Args:
        seats: [(x, y), ...] 좌석 좌표 목록
        fallback_row: 데이터 부족 시 사용할 row_tolerance 기본값
        fallback_gap: 데이터 부족 시 사용할 gap_tolerance 기본값

    Returns:
        (row_tolerance, gap_tolerance) 계산된 임계값
    """
    if len(seats) < 2:
        return fallback_row, fallback_gap

    # 0) y정렬 후 모든 y-gap 분석 → 행 간격 추정
    sorted_seats = sorted(seats, key=lambda s: s[1])
    y_gaps_raw: list[int] = []
    for i in range(1, len(sorted_seats)):
        gap = sorted_seats[i][1] - sorted_seats[i - 1][1]
        if gap > 0:
            y_gaps_raw.append(gap)

    if y_gaps_raw:
        # max y-gap = 행 간격 (within-row gap < between-row gap)
        estimated_row_gap = max(y_gaps_raw)
        # Adaptive threshold: 60% of row gap, min 10px
        # 0.6 × row_gap < row_gap → 행 병합 방지
        # ≥10px → 행 내 y변동 허용
        INITIAL_ROW_THRESHOLD = max(10, int(round(estimated_row_gap * 0.6)))
        logger.info(
            "  📐 적응형 행 임계값=%dpx (추정 행간=%dpx, %d개 y-gap 분석)",
            INITIAL_ROW_THRESHOLD, estimated_row_gap, len(y_gaps_raw),
        )
    else:
        INITIAL_ROW_THRESHOLD = 15
        logger.info("  📐 y-gap 데이터 없음 — 기본 행 임계값=15px")

    # 1) y 기준 행 그룹화 (adaptive threshold)
    row_groups: dict[int, list[int]] = {}
    for sx, sy in seats:
        matched = False
        for ry in row_groups:
            if abs(sy - ry) <= INITIAL_ROW_THRESHOLD:
                row_groups[ry].append(sx)
                matched = True
                break
        if not matched:
            row_groups[sy] = [sx]

    # 2. 각 행 내 x-gap 수집
    x_gaps: list[int] = []
    for ry, xs in row_groups.items():
        xs.sort()
        for i in range(1, len(xs)):
            gap = xs[i] - xs[i - 1]
            if gap > 0:
                x_gaps.append(gap)

    # 3. 행 간 y-gap 수집
    row_ys = sorted(row_groups.keys())
    y_gaps: list[int] = []
    for i in range(1, len(row_ys)):
        y_gaps.append(row_ys[i] - row_ys[i - 1])

    # 4. 충분한 데이터가 있는지 판단
    has_enough_x = len(x_gaps) >= 2
    has_enough_y = len(y_gaps) >= 1

    adaptive_row = fallback_row
    adaptive_gap = fallback_gap

    if has_enough_x:
        # median x-gap × 1.2
        median_x = statistics.median(x_gaps)
        adaptive_gap = max(1, int(round(median_x * 1.2)))
        logger.info(
            "  📐 적응형 gap_tolerance: %d (median x-gap=%d, n=%d)",
            adaptive_gap, median_x, len(x_gaps),
        )

    if has_enough_y:
        # median y-gap × 0.5
        median_y = statistics.median(y_gaps)
        adaptive_row = max(1, int(round(median_y * 0.5)))
        logger.info(
            "  📐 적응형 row_tolerance: %d (median y-gap=%d, n=%d)",
            adaptive_row, median_y, len(y_gaps),
        )

    if not has_enough_x and not has_enough_y:
        logger.info(
            "  📐 좌석 데이터 부족(%d석) — fallback 사용: row_tol=%d, gap_tol=%d",
            len(seats), fallback_row, fallback_gap,
        )

    return adaptive_row, adaptive_gap


def find_consecutive_seats(
    seats: list[tuple[int, int]],
    n: int = 2,
    row_tolerance: Optional[int] = None,
    gap_tolerance: Optional[int] = None,
) -> list[tuple[int, int]]:
    """
    빈 좌석 목록에서 **N연석** (연속된 N개 좌석) 찾기.

    row_tolerance와 gap_tolerance를 명시적으로 전달하지 않으면
    실제 좌석 좌표 분포를 분석하여 자동 계산한다 (_calc_adaptive_tolerances).

    Args:
        seats: find_seats_by_color() 결과 [(x, y), ...]
        n: 몇 연석? (2=2연석, 3=3연석...)
        row_tolerance: 같은 행 판단 y축 오차 (px). None이면 자동 계산.
        gap_tolerance: 좌석 간격 최대 (px). None이면 자동 계산.

    Returns:
        연석 그룹 [(x1,y1), (x2,y2), ...] 또는 빈 리스트
    """
    if len(seats) < n:
        logger.info("  🔍 빈 좌석 부족: %d개 < %d연석", len(seats), n)
        return []

    # 자동 계산 (명시적 값이 없을 때)
    if row_tolerance is None or gap_tolerance is None:
        auto_row, auto_gap = _calc_adaptive_tolerances(seats)
        if row_tolerance is None:
            row_tolerance = auto_row
        if gap_tolerance is None:
            gap_tolerance = auto_gap

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
                    if len(group) >= len(best_group):
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


# ============================================================
#  자동 좌석 색상 감지 — 설정된 색상으로 좌석을 못 찾았을 때 fallback
# ============================================================

_COMMON_SEAT_COLORS_BGR: list[str] = [
    "9980E1",   # 핑크 (티켓링크 일반 좌석)
    "C8C8C8",   # 회색 (전통적 빈좌석)
    "87CEEB",   # 하늘색 (다른 구역)
    "98FB98",   # 연두색
    "FFD700",   # 금색
    "FFA500",   # 주황색
    "FFFFFF",   # 흰색
]

def _auto_detect_seat_color(
    screenshot_bytes: bytes,
    area: Optional[tuple[int, int, int, int]] = None,
    tolerance: int = 30,
) -> str:
    """스크린샷에서 가장 많은 좌석 후보를 찾는 색상 자동 감지.

    미리 정의된 일반적인 좌석 색상 목록을 시도하여
    가장 많은 픽셀 클러스터를 생성하는 색상을 반환한다.

    Args:
        screenshot_bytes: 시스템 스크린샷 PNG 바이트
        area: 탐색 영역 (x1, y1, x2, y2)
        tolerance: 색상 오차범위

    Returns:
        BGR hex 문자열 (예: "9980E1") 또는 "" (실패 시)
    """
    img = Image.open(io.BytesIO(screenshot_bytes))
    pixels = np.array(img.convert("RGB"))
    h, w = pixels.shape[:2]
    if area:
        ax1, ay1, ax2, ay2 = area
        ax1 = max(0, min(ax1, w))
        ax2 = max(0, min(ax2, w))
        ay1 = max(0, min(ay1, h))
        ay2 = max(0, min(ay2, h))
        if ax1 > ax2: ax1, ax2 = ax2, ax1
        if ay1 > ay2: ay1, ay2 = ay2, ay1
        crop = pixels[ay1:ay2, ax1:ax2]
    else:
        crop = pixels

    best_color = ""
    best_count = 0

    for bgr_hex in _COMMON_SEAT_COLORS_BGR:
        target_rgb = (
            int(bgr_hex[4:6], 16),
            int(bgr_hex[2:4], 16),
            int(bgr_hex[0:2], 16),
        )
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

        mask = np.all((crop >= lower) & (crop <= upper), axis=-1)
        count = int(np.sum(mask))
        if count > best_count:
            best_count = count
            best_color = bgr_hex

    if best_color:
        logger.info(
            "  🎨 자동 색상 감지: %s (%dpx 일치, %d개 색상 시도)",
            best_color, best_count, len(_COMMON_SEAT_COLORS_BGR),
        )
    return best_color
