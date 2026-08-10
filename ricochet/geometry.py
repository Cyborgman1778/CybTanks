from __future__ import annotations

import math

from .models import Vec2


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def angle_difference(target: float, current: float) -> float:
    return (target - current + math.pi) % math.tau - math.pi


def turn_towards(current: float, target: float, maximum_step: float) -> float:
    difference = angle_difference(target, current)
    return current + clamp(difference, -maximum_step, maximum_step)


def point_segment_distance_squared(point: Vec2, start: Vec2, end: Vec2) -> float:
    segment = end - start
    length_squared = segment.length_squared()
    if length_squared == 0:
        return point.distance_squared_to(start)
    ratio = clamp((point - start).dot(segment) / length_squared, 0.0, 1.0)
    return point.distance_squared_to(start + segment * ratio)


def segment_distance_squared(first_start: Vec2, first_end: Vec2, second_start: Vec2, second_end: Vec2) -> float:
    first = first_end - first_start
    second = second_end - second_start
    denominator = first.cross(second)
    if abs(denominator) > 0.000_001:
        offset = second_start - first_start
        first_ratio = offset.cross(second) / denominator
        second_ratio = offset.cross(first) / denominator
        if 0.0 <= first_ratio <= 1.0 and 0.0 <= second_ratio <= 1.0:
            return 0.0
    return min(
        point_segment_distance_squared(first_start, second_start, second_end),
        point_segment_distance_squared(first_end, second_start, second_end),
        point_segment_distance_squared(second_start, first_start, first_end),
        point_segment_distance_squared(second_end, first_start, first_end),
    )


def oriented_box(center: Vec2, angle: float, half_length: float, half_width: float) -> list[Vec2]:
    forward = Vec2(math.cos(angle), math.sin(angle))
    side = Vec2(-forward.y, forward.x)
    return [
        center + forward * half_length + side * half_width,
        center + forward * half_length - side * half_width,
        center - forward * half_length - side * half_width,
        center - forward * half_length + side * half_width,
    ]
