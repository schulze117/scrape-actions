from shapely import MultiPolygon, Polygon
from shapely.geometry import box


def to_polygon(polygon_coords: list[list[tuple[float, float]]]) -> Polygon:
    shell = polygon_coords[0]
    holes = polygon_coords[1:] if len(polygon_coords) > 1 else None
    return Polygon(shell=shell, holes=holes)


def to_multipolygon(coordinates: list[list[list[tuple[float, float]]]]) -> MultiPolygon:
    return MultiPolygon([Polygon(shell=poly[0], holes=poly[1:] if len(poly) > 1 else None) for poly in coordinates])


def to_box(coordinates: tuple[float, float, float, float]) -> Polygon:
    return box(*coordinates)
