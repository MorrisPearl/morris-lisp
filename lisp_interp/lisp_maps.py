"""Maps, for the Lisp interpreter: the Census Bureau's boundaries of states,
counties, census tracts, ZIP code areas, and more (census-shapes), and maps
of them drawn with an equal-area projection (plot-map) -- each place
colored by a value, and a symbol drawn on each, sized by a value.

  (census-shapes level [:state s :year y :resolution r])
        the places of one kind -- states, counties, ... -- as a table: their
        codes (GEOID), names, land and water areas, and outlines
  (plot-map shapes [options])
        a map of them; it goes where every chart goes (a notebook, the GUI,
        or the console's summary), and save-chart saves it

The boundaries are the Census's cartographic boundary files
(https://www.census.gov/geographies/mapping-files.html): its boundaries
simplified for maps and clipped to the shoreline. Each is a zipped
"shapefile" -- a .shp file of outlines and a .dbf file of each place's
codes and name -- which this module reads itself. A file is downloaded
once and kept for good, since a year's boundaries never change (see
maps_directory). No key is needed.

A map is drawn with the Albers equal-area projection, so places' sizes on
the map are in proportion to their sizes on the ground. A map of the whole
country has the contiguous states in the projection usually used for them
(standard parallels 29.5 and 45.5 degrees north, centered on 96 degrees
west), and Alaska, Hawaii, and Puerto Rico each in its own, moved into the
empty corners below; Alaska is drawn at 35% of the scale, as on most maps
of the country. A map of anything smaller has one projection fitted to it.
"""

import datetime
import io
import math
import os
import struct
import zipfile

import numpy as np

from lisp_core import LispError, LispString, LispVector, NIL, Pair, keyword_options, pairs_to_list
from lisp_tables import column_values, column_vector, find_column, make_table_value, table_columns
from lisp_plot_chart import SYMBOLS, formatted_number, is_number, is_off, log_ticks, number_format, tick_text
import lisp_http

try:
    import matplotlib
    import matplotlib.path
    import matplotlib.patches
    import matplotlib.collections
    import matplotlib.colors
    import matplotlib.ticker
except ImportError:
    matplotlib = None           # (lisp_charts checks for matplotlib before anything is drawn)

BOUNDARIES_URL = "https://www2.census.gov/geo/tiger/GENZ{year}/shp/{name}.zip"
EARTH_RADIUS_KM = 6371.0

# The kinds of place, with the names they can be asked for by.
LEVEL_NAMES = {"nation": "nation", "state": "state", "county": "county", "tract": "tract",
               "place": "place", "zcta": "zcta", "zip": "zcta",
               "congressional-district": "congressional-district", "cd": "congressional-district",
               "metro-area": "metro-area", "cbsa": "metro-area"}
# Each kind's file name: {year}, {state}, {resolution}, and {congress} (a
# congressional district file is named for its Congress) are filled in.
FILE_NAMES = {"nation": "cb_{year}_us_nation_{resolution}",
              "state": "cb_{year}_us_state_{resolution}",
              "county": "cb_{year}_us_county_{resolution}",
              "congressional-district": "cb_{year}_us_cd{congress}_{resolution}",
              "metro-area": "cb_{year}_us_cbsa_{resolution}",
              "tract": "cb_{year}_{state}_tract_500k",       # a file for each state
              "place": "cb_{year}_{state}_place_500k",
              "zcta": "cb_2020_us_zcta520_500k"}            # drawn for each census: 2020's
PER_STATE = {"tract", "place"}
RESOLUTIONS = ["500k", "5m", "20m"]         # 1:500,000 (the most detail) to 1:20,000,000
CONGRESSES = [119, 118, 117, 116]           # the newest first

STATE_CODES = {   # postal abbreviation -> FIPS code
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10",
    "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19",
    "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35",
    "NY": "36", "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
    "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56", "AS": "60", "GU": "66", "MP": "69", "PR": "72", "VI": "78",
}


# ---------------------------------------------------------------------------
# Reading a shapefile
# ---------------------------------------------------------------------------

class Shape:
    """A place's outline: its rings, each a numpy array of (longitude,
    latitude) points -- the edge of each piece of it, and of any holes."""

    def __init__(self, rings):
        self.rings = rings

    def __str__(self):
        return "#<shape: %d ring%s>" % (len(self.rings), "" if len(self.rings) == 1 else "s")

    __repr__ = __str__


def read_shp(data, who):
    """The outlines in a .shp file's bytes: a list of each record's rings.
    The file is a 100-byte header, then the records; each is its number and
    length (big-endian), then its shape (little-endian): for a polygon, its
    type (5), bounding box, number of parts and points, where each part
    starts, and the points, as (x, y) pairs of doubles."""
    outlines = []
    position = 100
    while position < len(data):
        _, words = struct.unpack(">ii", data[position:position + 8])     # number, length in 16-bit words
        content = data[position + 8:position + 8 + 2 * words]
        position += 8 + 2 * words
        shape_type = struct.unpack("<i", content[:4])[0]
        if shape_type == 0:                                   # a record without a shape
            outlines.append([])
            continue
        if shape_type not in (5, 15, 25):                     # a polygon (15 and 25 also have Z or M values)
            raise LispError("%s: the file has shapes of type %d, not polygons" % (who, shape_type))
        parts, points = struct.unpack("<ii", content[36:44])
        starts = list(struct.unpack("<%di" % parts, content[44:44 + 4 * parts]))
        xy = np.frombuffer(content, dtype="<f8", count=2 * points, offset=44 + 4 * parts).reshape(points, 2)
        outlines.append([xy[start:end] for start, end in zip(starts, starts[1:] + [points])])
    return outlines


def dbf_value(text, kind):
    """A .dbf field's value: a number for a numeric field (None if it's
    blank), text for anything else."""
    if kind in "NF":
        if not text:
            return None
        number = float(text)
        return int(number) if number.is_integer() and "." not in text else number
    return LispString(text)


def read_dbf(data, encoding):
    """The records of a .dbf (dBase) file's bytes: the field names, and a
    row of values for each record. The header says how many records there
    are and how long; then come the fields' descriptions, 32 bytes each,
    ending with a 0x0D byte; then the records, each a deleted-or-not byte
    and then each field's text, in its fixed width."""
    count, header_length, record_length = struct.unpack("<IHH", data[4:12])
    fields = []                                 # (name, kind, width)
    position = 32
    while data[position] != 0x0D:
        name = data[position:position + 11].split(b"\0")[0].decode("ascii")
        fields.append((name, chr(data[position + 11]), data[position + 16]))
        position += 32
    rows = []
    for i in range(count):
        record = data[header_length + i * record_length:header_length + (i + 1) * record_length]
        offset, row = 1, []
        for name, kind, width in fields:
            row.append(dbf_value(record[offset:offset + width].decode(encoding, errors="replace").strip(), kind))
            offset += width
        rows.append(row)
    return [name for name, _, _ in fields], rows


def read_shapefile(data, who, path="the file"):
    """A zipped shapefile's bytes (from path): its field names (without the
    "20" that the 2020 ZIP code areas' end with: GEOID20 is GEOID), a row
    of values for each place, and each place's Shape."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise LispError("%s: %s isn't a zip file -- delete it, and it will be downloaded again" % (who, path))

    def member(ending):
        found = [name for name in archive.namelist() if name.lower().endswith(ending)]
        return archive.read(found[0]) if found else None
    shp, dbf, cpg = member(".shp"), member(".dbf"), member(".cpg")
    if shp is None or dbf is None:
        raise LispError("%s: the zip file has no shapefile (.shp and .dbf) in it" % who)
    names, rows = read_dbf(dbf, cpg.decode().strip() if cpg else "latin-1")
    outlines = read_shp(shp, who)
    if len(outlines) != len(rows):
        raise LispError("%s: the shapefile has %d outlines but %d records" % (who, len(outlines), len(rows)))
    names = [name[:-2] if name.endswith("20") else name for name in names]
    return names, rows, [Shape(rings) for rings in outlines]


# ---------------------------------------------------------------------------
# Downloading the Census's boundary files
# ---------------------------------------------------------------------------

def state_code(state, who):
    """A state's FIPS code, from its postal abbreviation ("NY") or its code
    (36, or "36")."""
    if is_number(state):
        return "%02d" % int(state)
    text = str(state).strip()
    if text.upper() in STATE_CODES:
        return STATE_CODES[text.upper()]
    if text.isdigit() and len(text) <= 2:
        return text.zfill(2)
    raise LispError("%s: %r isn't a state's postal abbreviation (\"NY\") or FIPS code (36)" % (who, text))


def maps_directory():
    """Where the boundary files are kept once they're downloaded -- for
    good, since a year's boundaries never change: ~/.cache/morris_lisp/maps,
    or the directory the LISP_MAPS_DIRECTORY environment variable names.
    Each file has the Census's own name, such as cb_2025_us_county_20m.zip.
    Delete one to free its space, or to have it downloaded again;
    http-clear-cache leaves them alone."""
    return (os.environ.get("LISP_MAPS_DIRECTORY")
            or os.path.join(os.path.expanduser("~"), ".cache", "morris_lisp", "maps"))


def boundary_file(level, state, year, resolution, who):
    """The bytes of the zipped boundary file for the level (and the state,
    for a level with a file for each state), and where it's kept. Without
    a year: the newest one already kept, or else the newest the Census
    has, which is then kept."""
    if level == "zcta":
        years = [2020]
    elif year is not None:
        years = [int(year)]
    else:
        this_year = datetime.date.today().year
        years = list(range(this_year, this_year - 6, -1))
    congresses = CONGRESSES if level == "congressional-district" else [None]
    candidates = [(candidate, FILE_NAMES[level].format(year=candidate, state=state, resolution=resolution,
                                                       congress=congress))
                  for candidate in years for congress in congresses]          # the newest first
    directory = maps_directory()
    for _, name in candidates:                  # one that's already kept: no need to ask the Census
        path = os.path.join(directory, name + ".zip")
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read(), path
    for candidate, name in candidates:
        try:
            data = lisp_http.download(BOUNDARIES_URL.format(year=candidate, name=name), 0, None, who)
        except LispError as e:
            if "HTTP 404" in str(e):              # no such file: try the next
                continue
            raise
        path = os.path.join(directory, name + ".zip")
        os.makedirs(directory, exist_ok=True)
        with open(path + ".part", "wb") as f:    # (then renamed, so a download cut short isn't kept)
            f.write(data)
        os.replace(path + ".part", path)
        return data, path
    raise LispError("%s: the Census has no %s boundary file%s at resolution %s%s" % (
        who, level, " for state %s" % state if state else "", resolution,
        " for %s" % years[0] if len(years) == 1 else " in the last few years"))


def census_shapes(level, *options):
    """(census-shapes level [:state s :year y :resolution r]) -- the places
    of one kind, from the Census Bureau's boundary files, as a table: a
    row for each, with its codes and names as the Census gives them
    (GEOID is its code; NAME its name; ALAND and AWATER its land and water
    areas, in square meters) and its outline (the shape column). The
    level is "state", "county", "tract" (census tracts), "place" (cities
    and towns), "zcta" (ZIP code areas), "congressional-district",
    "metro-area" (metropolitan and micropolitan areas), or "nation".
    :state picks one state's places, by postal abbreviation or code (a
    tract's or a place's level needs one). :resolution is "20m" (the
    simplest outlines), "5m", or "500k" (the most detailed); the default
    is 20m for the whole country, 500k for one state. :year picks the year
    (if not given, the newest already downloaded, or else the newest the
    Census has). A file is downloaded once, and kept for good (see
    maps_directory)."""
    who = "census-shapes"
    options = keyword_options(options, ["state", "year", "resolution"], who)
    level_name = str(level).lower()
    if level_name not in LEVEL_NAMES:
        raise LispError("%s: the levels are %s" % (who, ", ".join(sorted(set(LEVEL_NAMES.values())))))
    level = LEVEL_NAMES[level_name]
    state = state_code(options["state"], who) if options.get("state", NIL) is not NIL else None
    if level in PER_STATE and state is None:
        raise LispError("%s: the Census has a %s file for each state: give :state" % (who, level))
    if level in PER_STATE or level == "zcta":
        resolution = "500k"                       # the only one there is
    else:
        resolution = str(options.get("resolution") or ("500k" if state else "20m")).lower()
        if resolution not in RESOLUTIONS:
            raise LispError("%s: :resolution is one of %s" % (who, ", ".join(RESOLUTIONS)))
    data, path = boundary_file(level, state if level in PER_STATE else None, options.get("year"), resolution, who)
    names, rows, shapes = read_shapefile(data, who, path)

    if state and level not in PER_STATE:          # one state's places, from the file for the country
        if "STATEFP" not in names:
            raise LispError("%s: %s areas aren't divided by state, so :state can't pick them (use "
                            "table-filter on the table)" % (who, level))
        column = names.index("STATEFP")
        kept = [j for j, row in enumerate(rows) if row[column] == state]
        rows, shapes = [rows[j] for j in kept], [shapes[j] for j in kept]
    columns = [(name, column_vector([row[j] for row in rows])) for j, name in enumerate(names)]
    columns.append(("shape", LispVector(shapes)))
    return make_table_value(columns)


# ---------------------------------------------------------------------------
# The equal-area projection
# ---------------------------------------------------------------------------

def longitude_difference(lon, center_lon):
    """lon - center_lon, in degrees, the short way around the earth: from
    -180 to 180. (Alaska's Aleutian Islands cross the 180th meridian.)"""
    return (np.asarray(lon) - center_lon + 180) % 360 - 180


def albers(lon, lat, center_lon, origin_lat, parallel_1, parallel_2):
    """The Albers equal-area conic projection, on a sphere the size of the
    earth: longitudes and latitudes in degrees (numpy arrays) -> x and y in
    kilometers, east and north of (center_lon, origin_lat). Areas on the
    map are in proportion to areas on the ground; shapes are truest near
    the two standard parallels. (Snyder, Map Projections: A Working Manual,
    equations 14-1 to 14-4, for the sphere.)"""
    phi = np.radians(np.asarray(lat))
    phi0, phi1, phi2 = np.radians(origin_lat), np.radians(parallel_1), np.radians(parallel_2)
    n = (np.sin(phi1) + np.sin(phi2)) / 2
    c = np.cos(phi1) ** 2 + 2 * n * np.sin(phi1)
    rho0 = EARTH_RADIUS_KM * np.sqrt(c - 2 * n * np.sin(phi0)) / n
    rho = EARTH_RADIUS_KM * np.sqrt(c - 2 * n * np.sin(phi)) / n
    theta = n * np.radians(longitude_difference(lon, center_lon))
    return rho * np.sin(theta), rho0 - rho * np.cos(theta)


def west_longitudes(lon):
    """Longitudes as degrees west of Greenwich, all negative: the few places
    past the 180th meridian (Alaska's far Aleutians, Guam) as less than
    -180, so a place's longitudes don't jump from -179 to 179."""
    lon = np.asarray(lon)
    return np.where(lon > 0, lon - 360, lon)


def place_region(shape):
    """Where a place is, for a map of the whole country: "alaska", "hawaii",
    "puerto rico" (with the Virgin Islands), "pacific" (Guam, American
    Samoa, the Northern Mariana Islands), or "contiguous" -- by the middle
    of its points. None for a place without an outline."""
    if not shape.rings:
        return None
    points = np.vstack(shape.rings)
    lon, lat = west_longitudes(points[:, 0]).mean(), points[:, 1].mean()
    if lat > 50 and lon < -129:
        return "alaska"
    if 15 < lat < 30 and -180 < lon < -150:
        return "hawaii"
    if 17 < lat < 19 and -68 < lon < -64:
        return "puerto rico"
    if lon < -130 or lat < 15:
        return "pacific"
    return "contiguous"


# The projections for a map of the whole country: region -> (center
# longitude, origin latitude, standard parallels, scale), and where each
# inset goes: the middle of a point in it, as fractions of the contiguous
# states' width and height from their lower-left corner.
NATIONAL_PROJECTIONS = {"contiguous": (-96.0, 37.5, 29.5, 45.5, 1.0),
                        "alaska": (-154.0, 50.0, 55.0, 65.0, 0.35),
                        "hawaii": (-157.0, 13.0, 8.0, 18.0, 1.0),
                        "puerto rico": (-66.5, 18.0, 17.0, 19.0, 1.0)}
INSETS = {"alaska": ((-152.0, 63.5), (0.12, 0.10)),      # (a point in it, where that point goes)
          "hawaii": ((-157.5, 20.5), (0.30, 0.05)),
          "puerto rico": ((-66.4, 18.2), (0.85, 0.02))}


def ring_area(ring):
    """A ring's area (by the shoelace formula), in the units of its points
    squared; positive or negative, by the way it goes around."""
    x, y = ring[:, 0], ring[:, 1]
    return (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2


def map_projection(shapes):
    """A function that puts a place's outline on the map -- its rings,
    projected, or None for a place that isn't drawn -- for a map of these
    shapes: the national layout, if they're the contiguous states and
    Alaska, Hawaii, or Puerto Rico; otherwise one projection fitted to
    them."""
    regions = {place_region(shape) for shape in shapes} - {None}
    if "contiguous" in regions and regions & set(INSETS):
        return national_projection(shapes)
    every_point = np.vstack([ring for shape in shapes for ring in shape.rings])
    lon, lat = west_longitudes(every_point[:, 0]), every_point[:, 1]
    south, north = lat.min(), lat.max()
    center_lon, origin_lat = (lon.min() + lon.max()) / 2, (south + north) / 2
    parallel_1, parallel_2 = south + (north - south) / 6, north - (north - south) / 6
    if abs(parallel_1 + parallel_2) < 1e-6:     # (parallels either side of the equator: none)
        parallel_2 += 1

    def project(shape):
        return [np.column_stack(albers(ring[:, 0], ring[:, 1], center_lon, origin_lat, parallel_1, parallel_2))
                for ring in shape.rings] or None
    return project


def national_projection(shapes):
    """The national layout: the contiguous states in their usual Albers
    projection, and Alaska, Hawaii, and Puerto Rico each in its own, scaled
    and moved to its place below them. The island areas in the Pacific
    aren't drawn."""
    def projected(shape, region):
        center_lon, origin_lat, parallel_1, parallel_2, scale = NATIONAL_PROJECTIONS[region]
        return [scale * np.column_stack(albers(ring[:, 0], ring[:, 1], center_lon, origin_lat, parallel_1, parallel_2))
                for ring in shape.rings]

    contiguous = np.vstack([ring for shape in shapes if place_region(shape) == "contiguous"
                            for ring in projected(shape, "contiguous")])
    left, bottom = contiguous.min(axis=0)
    width, height = contiguous.max(axis=0) - (left, bottom)
    offsets = {"contiguous": np.zeros(2)}
    for region, ((lon, lat), (across, up)) in INSETS.items():
        center_lon, origin_lat, parallel_1, parallel_2, scale = NATIONAL_PROJECTIONS[region]
        x, y = albers(lon, lat, center_lon, origin_lat, parallel_1, parallel_2)
        offsets[region] = np.array([left + across * width, bottom + up * height]) - scale * np.array([x, y])

    def project(shape):
        region = place_region(shape)
        if region not in offsets:
            return None
        return [ring + offsets[region] for ring in projected(shape, region)]
    return project


def center_of(rings):
    """Where a place's symbol goes: the center (centroid) of its largest
    piece, so an island doesn't pull it out to sea."""
    largest = max(rings, key=lambda ring: abs(ring_area(ring)))
    area = ring_area(largest)
    if abs(area) < 1e-12:
        return largest.mean(axis=0)
    x, y = largest[:, 0], largest[:, 1]
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    return np.array([np.sum((x + np.roll(x, -1)) * cross), np.sum((y + np.roll(y, -1)) * cross)]) / (6 * area)


# ---------------------------------------------------------------------------
# Building a map's spec
# ---------------------------------------------------------------------------

MAP_OPTIONS = ["title", "data", "key", "fill", "fill-label", "colors", "log", "fill-min", "fill-max", "format",
               "symbols", "symbol-label", "symbols-on", "symbol-data", "symbol-key", "symbol-size", "symbol-color",
               "symbol", "borders", "edge-color", "edge-width", "legend", "width", "height"]
DATA_KEYS = ["GEOID", "fips", "geoid", "zip", "zcta"]      # a data table's code column, if :key doesn't say
LEGEND_SHARE = [1, 1 / 4, 1 / 16]                           # the symbol legend's values, of the largest


def shapes_and_codes(table, who, what):
    """A table from census-shapes: its Shape for each row, and each row's
    code (GEOID)."""
    columns = table_columns(table, who)
    names = [name for name, _ in columns]
    if "shape" not in names or "GEOID" not in names:
        raise LispError("%s: %s must be a table from census-shapes (with GEOID and shape columns)" % (who, what))
    shapes = column_values(find_column(columns, "shape", who))
    if not all(isinstance(shape, Shape) for shape in shapes):
        raise LispError("%s: %s's shape column must hold census-shapes' outlines" % (who, what))
    return shapes, [str(code) for code in column_values(find_column(columns, "GEOID", who))]


def normalized_code(value, width):
    """A place's code from a table of data, written as the shapes' GEOIDs
    are: text, zero-padded to their width (a state's 6 is "06"), and a
    state's 5-character BEA code ("36000") as its 2 digits."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if text.isdigit():
        if len(text) < width:
            text = text.zfill(width)
        elif width == 2 and len(text) == 5 and text.endswith("000"):
            text = text[:2]
    return text


def number_or_none(value):
    if is_number(value) and not (isinstance(value, float) and math.isnan(value)):
        return float(value)
    return None


def values_for_places(table, codes, data, key, column, who):
    """The values of a column for each place: the shapes table's own column,
    without data; or the column of the data table, matched to the places by
    the data's codes -- the key column, or the key columns' values joined
    ("36" and "061" are "36061") -- with None where the data has no value."""
    if data is None:
        values = column_values(find_column(table_columns(table, who), str(column), who))
        return [number_or_none(v) for v in values]
    data_columns = table_columns(data, who)
    names = [name for name, _ in data_columns]
    if key is None:
        key = next((name for name in DATA_KEYS if name in names), None)
        if key is None:
            raise LispError("%s: give :key, the data's column of places' codes (it has no %s column)"
                            % (who, " or ".join(DATA_KEYS)))
    key_names = [str(k) for k in pairs_to_list(key)] if isinstance(key, Pair) else [str(key)]
    key_values = [column_values(find_column(data_columns, name, who)) for name in key_names]
    width = max(set(len(code) for code in codes), key=[len(code) for code in codes].count)   # the usual width
    values = column_values(find_column(data_columns, str(column), who))
    by_code = {}
    for row, value in enumerate(values):
        code = normalized_code("".join(str(normalized_code(k[row], 0)) for k in key_values), width)
        if code in by_code:
            raise LispError("%s: the data has more than one row for %s (add them up first, with table-group-by)"
                            % (who, code))
        by_code[code] = number_or_none(value)
    return [by_code.get(code) for code in codes]


def projected_shapes(shapes, project):
    """Each place's rings on the map (None for a place that isn't drawn)."""
    return [project(shape) if shape.rings else None for shape in shapes]


def round_number_below(value):
    """The largest of 1, 2, 2.5, and 5 times a power of 10 that is no more
    than value: 217,075 -> 200,000."""
    power = 10.0 ** math.floor(math.log10(value))
    return max(m * power for m in (1, 2, 2.5, 5, 10) if m * power <= value * (1 + 1e-9))


def build_map_spec(shapes_table, options, who="plot-map"):
    """The spec for (plot-map shapes [options])."""
    options = keyword_options(options, MAP_OPTIONS, who)
    shapes, codes = shapes_and_codes(shapes_table, who, "the shapes")
    project = map_projection([shape for shape in shapes if shape.rings])
    on_map = projected_shapes(shapes, project)
    drawn = [j for j, rings in enumerate(on_map) if rings]
    if not drawn:
        raise LispError("%s: there are no places to draw" % who)
    data = options.get("data")
    key = options.get("key")
    value_format = number_format(options.get("format"), who, ":format")

    fill = None
    if options.get("fill") is not None:
        values = values_for_places(shapes_table, codes, data, key, options["fill"], who)
        log = not is_off(options.get("log", False))
        present = [values[j] for j in drawn if values[j] is not None]
        if log and any(v <= 0 for v in present):
            raise LispError("%s: a log scale (:log #t) needs values above 0" % who)
        colors = str(options.get("colors", "viridis"))
        if matplotlib is not None and colors not in matplotlib.colormaps:
            raise LispError("%s: %r isn't one of matplotlib's color maps, such as \"viridis\", \"Blues\", "
                            "\"YlOrRd\", or \"RdBu\"" % (who, colors))
        fill = {"label": str(options.get("fill-label", options["fill"])), "column": str(options["fill"]),
                "values": [values[j] for j in drawn], "colors": colors,
                "log": log, "min": options.get("fill-min"), "max": options.get("fill-max")}

    symbols = None
    if options.get("symbols") is not None:
        if options.get("symbols-on") is not None:
            symbol_table = options["symbols-on"]
            symbol_shapes, symbol_codes = shapes_and_codes(symbol_table, who, ":symbols-on")
            symbol_rings = projected_shapes(symbol_shapes, project)
        else:
            symbol_table, symbol_codes, symbol_rings = shapes_table, codes, on_map
        values = values_for_places(symbol_table, symbol_codes, options.get("symbol-data", data),
                                   options.get("symbol-key", key), options["symbols"], who)
        points = [(center_of(rings), value) for rings, value in zip(symbol_rings, values)
                  if rings and value is not None and value > 0]       # (a symbol can't be smaller than nothing)
        symbol = str(options.get("symbol", "circle"))
        if symbol not in SYMBOLS:
            raise LispError("%s: there's no symbol %r -- the symbols are %s" % (who, symbol, ", ".join(SYMBOLS)))
        size = options.get("symbol-size", 24)
        if not (is_number(size) and size > 0):
            raise LispError("%s: :symbol-size is the largest symbol's width, in points: a number above 0" % who)
        largest = max((value for _, value in points), default=None)
        symbols = {"label": str(options.get("symbol-label", options["symbols"])), "column": str(options["symbols"]),
                   "points": [(float(c[0]), float(c[1]), v) for c, v in points],
                   "largest": largest, "size": float(size), "color": str(options.get("symbol-color", "C3")),
                   "symbol": symbol,
                   "legend_values": sorted({round_number_below(largest * share) for share in LEGEND_SHARE},
                                           reverse=True) if largest else []}

    borders = []
    if options.get("borders") is not None:
        border_shapes, _ = shapes_and_codes(options["borders"], who, ":borders")
        borders = [rings for rings in projected_shapes(border_shapes, project) if rings]

    every_point = np.vstack([ring for j in drawn for ring in on_map[j]])
    (left, bottom), (right, top) = every_point.min(axis=0), every_point.max(axis=0)
    margin = 0.02 * max(right - left, top - bottom)
    if symbols:                 # just the symbols on the map: not those on places off it
        symbols["points"] = [(x, y, v) for x, y, v in symbols["points"]
                             if left - margin <= x <= right + margin and bottom - margin <= y <= top + margin]
    width = float(options.get("width") or 8.0)
    height = options.get("height")
    if height is None:      # as tall as the map is, for its width (and room for the title and legends)
        height = min(12.0, max(3.0, 0.85 * width * (top - bottom) / (right - left) + 1.0))
    return {"kind": "map",
            "title": str(options.get("title", "")),
            "width": width, "height": float(height),
            "extent": (left - margin, right + margin, bottom - margin, top + margin),
            "places": [{"rings": on_map[j]} for j in drawn],
            "fill": fill, "symbols": symbols, "borders": borders, "format": value_format,
            "edge_color": str(options.get("edge-color", "white" if fill else "gray")),
            "edge_width": float(options.get("edge-width", 0.3 if fill else 0.5)),
            "legend": not is_off(options.get("legend", True))}


# ---------------------------------------------------------------------------
# Drawing a map
# ---------------------------------------------------------------------------

PLAIN_COLOR = "#eeeeee"         # a place, on a map that isn't colored by a value
NO_DATA_COLOR = "#c8c8c8"       # a place with no value, on one that is
BORDER_COLOR = "#333333"


def outline_path(rings):
    """One path of all a place's rings, so its holes stay holes."""
    return matplotlib.path.Path.make_compound_path(*[matplotlib.path.Path(ring, closed=True) for ring in rings])


def value_text(value, spec):
    """A value in a legend: in the map's :format, or written plainly."""
    return formatted_number(value, spec["format"]) if spec["format"] else tick_text(value)


def draw(fig, ax, spec):
    """Draw a map spec on ax: the places (colored by their values, if
    there are any), the borders, the symbols (largest first, so the small
    ones stay in sight), and the legends: a color bar beside the map, and
    the symbols' sizes (and the color of a place with no value) below."""
    ax.clear()
    ax.set_aspect("equal")
    ax.set_axis_off()
    places = matplotlib.collections.PatchCollection(
        [matplotlib.patches.PathPatch(outline_path(place["rings"])) for place in spec["places"]],
        edgecolor=spec["edge_color"], linewidth=spec["edge_width"])
    fill = spec["fill"]
    legend_entries = []
    if fill:
        values = np.array([np.nan if v is None else v for v in fill["values"]])
        colors = matplotlib.colormaps[fill["colors"]].with_extremes(bad=NO_DATA_COLOR)    # (no value: gray)
        low = fill["min"] if fill["min"] is not None else np.nanmin(values) if np.isfinite(values).any() else 0
        high = fill["max"] if fill["max"] is not None else np.nanmax(values) if np.isfinite(values).any() else 1
        norm = (matplotlib.colors.LogNorm if fill["log"] else matplotlib.colors.Normalize)(vmin=low, vmax=high)
        places.set_array(np.ma.masked_invalid(values))
        places.set_cmap(colors)
        places.set_norm(norm)
        if np.isnan(values).any():
            legend_entries.append((matplotlib.patches.Patch(facecolor=NO_DATA_COLOR), "no data"))
    else:
        places.set_facecolor(PLAIN_COLOR)
    ax.add_collection(places)

    if spec["borders"]:
        ax.add_collection(matplotlib.collections.PatchCollection(
            [matplotlib.patches.PathPatch(outline_path(rings)) for rings in spec["borders"]],
            facecolor="none", edgecolor=BORDER_COLOR, linewidth=0.8))

    symbols = spec["symbols"]
    if symbols and symbols["points"]:
        def area(value):                        # in points squared: in proportion to the value
            return symbols["size"] ** 2 * value / symbols["largest"]
        points = sorted(symbols["points"], key=lambda p: -p[2])
        style = dict(marker=SYMBOLS[symbols["symbol"]], color=symbols["color"], alpha=0.6,
                     edgecolors="white", linewidths=0.5)
        ax.scatter([p[0] for p in points], [p[1] for p in points], s=[area(p[2]) for p in points],
                   zorder=3, **style)
        for value in symbols["legend_values"]:
            legend_entries.append((ax.scatter([], [], s=area(value), **style), value_text(value, spec)))

    left, right, bottom, top = spec["extent"]
    ax.set_xlim(left, right)
    ax.set_ylim(bottom, top)
    ax.set_title(spec["title"])
    if spec["legend"]:
        if fill:
            bar = fig.colorbar(places, ax=ax, shrink=0.6, pad=0.02)
            if fill["log"]:                     # ticks at round numbers, with nothing written between them
                bar.ax.yaxis.set_major_locator(matplotlib.ticker.FixedLocator(log_ticks(norm.vmin, norm.vmax, 6)))
                bar.ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
            bar.ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: value_text(v, spec)))
            bar.set_label(fill["label"])
        if legend_entries:
            ax.legend([drawn for drawn, _ in legend_entries], [label for _, label in legend_entries],
                      title=symbols["label"] if symbols else None, loc="upper center",
                      bbox_to_anchor=(0.5, 0.0), ncol=len(legend_entries), frameon=False,
                      borderpad=1.0, handletextpad=0.6, columnspacing=1.8)
    fig.tight_layout()


def summary_text(spec):
    """What the console shows for a map, in place of drawing it."""
    lines = [("[map] " + spec["title"]).rstrip(), "  %d places" % len(spec["places"])]
    if spec["fill"]:
        colored = sum(1 for v in spec["fill"]["values"] if v is not None)
        lines[-1] += ", %d colored by %s" % (colored, spec["fill"]["column"])
    if spec["symbols"]:
        lines.append("  %d symbols, sized by %s" % (len(spec["symbols"]["points"]), spec["symbols"]["column"]))
    return "\n".join(lines) + "\n"


BUILTINS = {
    "census-shapes": census_shapes,
}
