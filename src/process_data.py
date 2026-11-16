"""
DBA5103 group project - Data processing (baseline inputs)
Region: WEST COAST-JURONG WEST GRC (Electoral Boundary 2025)

Steps
1. Load NEA hawker centres + 2025 electoral boundaries (data.gov.sg GeoJSON).
2. Keep hawker centres located inside the WEST COAST-JURONG WEST boundary.
3. Keep only centres that are operating (STATUS starts with "Existing") and have
   at least one cooked-food stall; verify this with assertions.
4. Add a depot (start/end point of the inspection route).
5. Query OSRM Table service for road travel-time and distance matrices.
6. Save clean CSVs + a map of the depot and chosen hawker centres.

Outputs
- nodes.csv              : node 0 = depot, nodes 1..N = hawker centres
- time_matrix_min.csv    : driving time in minutes, row i -> column j (free flow, no traffic)
- distance_matrix_km.csv : driving distance in km, row i -> column j
- map.png                : map of the nodes, in image format
"""
import json
import os

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "data", "raw")
PROCESSED = os.path.join(HERE, "..", "data", "processed")
os.makedirs(PROCESSED, exist_ok=True)

REGION = "WEST COAST-JURONG WEST"
# Operating centres: NEA uses "Existing", "Existing (new)" and "Existing (replacement)".
# Other values ("Under Construction", "Interim Centre") are excluded.
OPERATING_PREFIX = "Existing"

# Depot = start and end point of the route (team decision).
# West Coast-Jurong West Town Council, Boon Lay Office, 325 Boon Lay Place.
# Inside the GRC boundary. Coordinates from OneMap search API (postal code 649886).
DEPOT = {
    "name": "DEPOT - West Coast-Jurong West Town Council (Boon Lay Office)",
    "address": "325 Boon Lay Place, Singapore 649886",
    "postal_code": "649886",
    "lat": 1.345433917027935,
    "lon": 103.714106395859,
}
DEPOT_SHORT = "Depot - Town Council (Boon Lay)"

OSRM_URL = "https://router.project-osrm.org/table/v1/driving/"


# ---------------------------------------------------------------- geometry
def point_in_ring(x, y, ring):
    """Ray-casting test: is point (x, y) inside a closed ring of [x, y] points?"""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def point_in_geometry(x, y, geom):
    polygons = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    for poly in polygons:
        outer, holes = poly[0], poly[1:]
        if point_in_ring(x, y, outer) and not any(point_in_ring(x, y, h) for h in holes):
            return True
    return False


# ---------------------------------------------------------------- 1-3. hawkers
def load_hawkers():
    with open(os.path.join(RAW, "HawkerCentresGEOJSON.geojson"), encoding="utf-8") as f:
        hawkers = json.load(f)["features"]
    with open(os.path.join(RAW, "ElectoralBoundary2025GEOJSON.geojson"), encoding="utf-8") as f:
        boundaries = json.load(f)["features"]

    region = next(b for b in boundaries if b["properties"]["ED_DESC"] == REGION)

    rows = []
    for h in hawkers:
        lon, lat = h["geometry"]["coordinates"][:2]
        if not point_in_geometry(lon, lat, region["geometry"]):
            continue
        p = h["properties"]
        rows.append({
            "name": p["NAME"].strip(),
            "address": p["ADDRESS_MYENV"],
            "postal_code": p["ADDRESSPOSTALCODE"],
            "status": p["STATUS"],
            "cooked_food_stalls": p["NUMBER_OF_COOKED_FOOD_STALLS"],
            "lat": lat,
            "lon": lon,
        })

    # number nodes geographically, west -> east (longitude), so IDs are easy to read on the map
    df = pd.DataFrame(rows).sort_values("lon").reset_index(drop=True)
    print(f"Hawker centres inside {REGION}: {len(df)}\n")
    print(df[["name", "status", "cooked_food_stalls"]].to_string() + "\n")

    operating = df["status"].str.startswith(OPERATING_PREFIX)
    has_stalls = df["cooked_food_stalls"].fillna(0) > 0
    for r in df[~operating].itertuples():
        print(f"Excluded (not operating, status = {r.status}): {r.name}")
    for r in df[operating & ~has_stalls].itertuples():
        print(f"Excluded (0 cooked-food stalls): {r.name}")

    kept = df[operating & has_stalls].reset_index(drop=True)

    # verification: every centre kept is operating and has cooked-food stalls
    assert kept["status"].str.startswith(OPERATING_PREFIX).all(), "non-operating centre kept"
    assert (kept["cooked_food_stalls"] > 0).all(), "centre with 0 cooked-food stalls kept"
    print(f"\nVerified: {len(kept)} hawker centres kept, all operating "
          f"(status: {sorted(kept['status'].unique())}) and all with > 0 cooked-food stalls.")
    return region, kept


# ---------------------------------------------------------------- 4. nodes
def build_nodes(hawkers):
    depot = pd.DataFrame([{**DEPOT, "status": "Depot", "cooked_food_stalls": 0}])
    nodes = pd.concat([depot, hawkers], ignore_index=True)
    nodes.insert(0, "node_id", range(len(nodes)))
    nodes.insert(1, "type", ["depot"] + ["hawker"] * len(hawkers))
    nodes.insert(3, "short_name", nodes["name"].map(short_name))
    return nodes


def short_name(name):
    """Readable label: the name in brackets if there is one, e.g.
    'West Coast Drive Blk 503 (Ayer Rajah Food Centre)' -> 'Ayer Rajah Food Centre'."""
    if name.startswith("DEPOT"):
        return DEPOT_SHORT
    if "(" in name and name.endswith(")"):
        return name[name.index("(") + 1:-1]
    return name


# ---------------------------------------------------------------- 5. OSRM
def osrm_matrices(nodes):
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in zip(nodes["lon"], nodes["lat"]))
    r = requests.get(OSRM_URL + coords, params={"annotations": "duration,distance"}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok":
        raise RuntimeError(data)
    ids = nodes["node_id"].tolist()
    time_min = pd.DataFrame(data["durations"], index=ids, columns=ids) / 60.0
    dist_km = pd.DataFrame(data["distances"], index=ids, columns=ids) / 1000.0
    # how far OSRM had to move each point to reach the road network (sanity check)
    snap_m = [round(s["distance"], 1) for s in data["sources"]]
    return time_min.round(2), dist_km.round(3), snap_m


LABEL_POS = {
    DEPOT_SHORT: (12, -2, "left", "center"),
    "Boon Lay Place Market and Food Village": (-10, 0, "right", "center"),
    "Jurong West Street 52 Blk 505": (8, 6, "left", "bottom"),
    "Jurong West Hawker Centre": (0, -12, "center", "top"),
    "Taman Jurong Market and Food Centre": (12, 0, "left", "center"),
    "Teban Gardens Market and Food Centre": (8, 6, "left", "bottom"),
    "Ayer Rajah Food Centre": (-12, 0, "right", "center"),
    "Clementi West Street 2 Blk 726": (-10, -6, "right", "top"),
}


def write_static_map(nodes, region, path):
    """PNG version of the map (for the report)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 7))
    geom = region["geometry"]
    polygons = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    for poly in polygons:
        xs, ys = zip(*[(c[0], c[1]) for c in poly[0]])
        ax.fill(xs, ys, color="#e8eef7", edgecolor="#555", linewidth=0.8)
    h = nodes[nodes["type"] == "hawker"]
    d = nodes[nodes["type"] == "depot"]
    ax.scatter(h["lon"], h["lat"], s=40 + h["cooked_food_stalls"] * 3, c="#1f6feb",
               alpha=0.8, label="Hawker centre (size = cooked-food stalls)", zorder=3)
    ax.scatter(d["lon"], d["lat"], s=160, marker="*", c="#c0392b", label="Depot", zorder=4)
    for r in nodes.itertuples():
        # label position (offset in points, alignment) chosen by hand so labels don't overlap
        dx, dy, ha, va = LABEL_POS.get(r.short_name, (8, 6, "left", "bottom"))
        ax.annotate(f"{r.node_id} · {r.short_name}", (r.lon, r.lat), xytext=(dx, dy),
                    textcoords="offset points", fontsize=9, ha=ha, va=va,
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))
    ax.set_xlim(nodes["lon"].min() - 0.025, nodes["lon"].max() + 0.03)
    ax.set_ylim(nodes["lat"].min() - 0.015, nodes["lat"].max() + 0.015)
    ax.set_aspect("equal")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Hawker centres in West Coast-Jurong West GRC")
    ax.legend(loc="lower left", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    region, hawkers = load_hawkers()

    depot_ok = point_in_geometry(DEPOT["lon"], DEPOT["lat"], region["geometry"])
    print(f"Depot inside region boundary: {depot_ok}")

    nodes = build_nodes(hawkers)
    time_min, dist_km, snap_m = osrm_matrices(nodes)
    nodes["osrm_snap_m"] = snap_m

    nodes.to_csv(os.path.join(PROCESSED, "nodes.csv"), index=False)
    time_min.to_csv(os.path.join(PROCESSED, "time_matrix_min.csv"), index_label="from\\to")
    dist_km.to_csv(os.path.join(PROCESSED, "distance_matrix_km.csv"), index_label="from\\to")
    write_static_map(nodes, region, os.path.join(PROCESSED, "map.png"))

    print("\nNodes:")
    print(nodes[["node_id", "type", "short_name", "cooked_food_stalls", "osrm_snap_m"]].to_string(index=False))
    print("\nTravel time (min):")
    print(time_min.to_string())
    print("\nDistance (km):")
    print(dist_km.to_string())
    print(f"\nSaved to {PROCESSED}")
