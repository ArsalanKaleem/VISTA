"""Day 24: coverage by district / tehsil, atlas sheets and an interactive QC map.

    python scripts/coverage_report.py              # tables + map (+ atlas if zones/v1 exist)

Coverage definitions (documentation/coverage_report.md repeats them):
  building coverage   buildings inside Q1-Q2 rural hamlets / all Open Buildings in the tehsil that are not in
                      an urban-class cluster. The denominator includes buildings in Q3 hamlets and in groups
                      of fewer than 5 buildings, so it is the share of rural built fabric the model population
                      represents. Computed from files, not assumed.
  PBS comparison      hamlets and village-tier units per PBS 2020 settlement, per OCHA tehsil (comparison
                      only, PBS is not ground truth).
  matching accuracy   precision / recall from the Day 21-22 validation sample: NOT DONE, columns are blank.

Outputs
  outputs/tables/coverage_by_district.csv, coverage_by_tehsil.csv
  outputs/maps/interactive_map.html         Leaflet, tehsil choropleth + pilot-taluka hamlets for QC
  outputs/maps/atlas_v0.1.pdf               20 sheets: hamlet, core, resource, connectivity, buildings, roads
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VI = ROOT / "data/village_inventory"
ZV1 = VI / "zones/v1"
TAB = ROOT / "outputs/tables"
MAPS = ROOT / "outputs/maps"
CRS = 32642
PILOT_PCODES = {"PK72605", "PK71803", "PK72204"}  # Mithi, Sanghar, Shah Bunder (OCHA)


def tables(reg: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    fp = pd.read_parquet(VI / "raw/footprints.parquet", columns=["adm3_pcode"])
    all_b = fp.groupby("adm3_pcode").size().rename("buildings_all")
    urban_b = reg[~reg.in_rural_population].groupby("adm3_pcode").n_buildings.sum().rename("buildings_urban_clusters")
    r = reg[reg.in_rural_population]
    g = r.groupby("adm3_pcode")
    t = pd.DataFrame({
        "hamlets_rural": g.size(), "villages_rural": g.vvid.nunique(),
        "q1": g.quality_class.apply(lambda s: (s == "Q1").sum()), "q2": g.quality_class.apply(lambda s: (s == "Q2").sum()),
        "q3": g.quality_class.apply(lambda s: (s == "Q3").sum()),
        "buildings_rural_hamlets": g.n_buildings.sum(),
        "buildings_q12": g.apply(lambda d: d[d.quality_class != "Q3"].n_buildings.sum(), include_groups=False),
        "named_share": g.name.apply(lambda s: s.notna().mean()).round(3),
        "with_deh_share": g.deh.apply(lambda s: s.notna().mean()).round(3),
    })
    t = t.join(all_b).join(urban_b)
    t["buildings_urban_clusters"] = t.buildings_urban_clusters.fillna(0).astype(int)
    t["buildings_rural_all"] = t.buildings_all - t.buildings_urban_clusters
    t["building_coverage_q12"] = (t.buildings_q12 / t.buildings_rural_all).round(3)
    t["hamlets_excluded_urban"] = reg[~reg.in_rural_population].groupby("adm3_pcode").size().reindex(t.index).fillna(0).astype(int)
    o3 = gpd.read_file(VI / "admin/admin_boundaries.gpkg", layer="ocha_adm3")[["adm3_pcode", "adm3_name", "adm2_name"]]
    t = o3.set_index("adm3_pcode").join(t, how="left")
    cw = pd.read_csv(VI / "admin/taluka_crosswalk.csv")
    t12 = pd.read_csv(VI / "pbs_sindh_tables/t1_2_settlements.csv")
    t12 = t12[t12.level == "taluka"][["name", "rural_populated_mouzas", "settlements_total"]]
    pbs = cw.dropna(subset=["ocha_adm3_pcode"]).merge(t12, left_on="pbs_taluka", right_on="name", how="left") \
        .drop_duplicates("ocha_adm3_pcode").set_index("ocha_adm3_pcode")[["rural_populated_mouzas", "settlements_total"]]
    dehs = pd.read_csv(VI / "deh/deh_counts_by_taluka.csv").dropna(subset=["ocha_pcode"]).set_index("ocha_pcode").bor_dehs
    t = t.join(pbs.rename(columns={"rural_populated_mouzas": "pbs_mouzas_2020", "settlements_total": "pbs_settlements_2020"}))
    t["bor_dehs"] = dehs.reindex(t.index)
    t["villages_per_pbs_settlement"] = (t.villages_rural / t.pbs_settlements_2020).round(2)
    t["hamlets_per_pbs_settlement"] = (t.hamlets_rural / t.pbs_settlements_2020).round(2)
    t["validation_precision"] = np.nan   # Day 22
    t["validation_recall"] = np.nan      # Day 22
    t = t.reset_index()
    num = ["hamlets_rural", "villages_rural", "q1", "q2", "q3", "buildings_rural_hamlets", "buildings_q12", "buildings_all",
           "buildings_urban_clusters", "buildings_rural_all", "hamlets_excluded_urban", "pbs_mouzas_2020",
           "pbs_settlements_2020", "bor_dehs"]
    d = t.groupby("adm2_name")[num].sum(min_count=1).reset_index()
    d["q12_share"] = ((d.q1 + d.q2) / d.hamlets_rural).round(3)
    d["building_coverage_q12"] = (d.buildings_q12 / d.buildings_rural_all).round(3)
    d["villages_per_pbs_settlement"] = (d.villages_rural / d.pbs_settlements_2020).round(2)
    d["hamlets_per_pbs_settlement"] = (d.hamlets_rural / d.pbs_settlements_2020).round(2)
    d["validation_precision"], d["validation_recall"] = np.nan, np.nan
    return t, d


def interactive_map(t: pd.DataFrame, reg: gpd.GeoDataFrame) -> None:
    o3 = gpd.read_file(VI / "admin/admin_boundaries.gpkg", layer="ocha_adm3").to_crs(CRS)
    o3["geometry"] = o3.geometry.simplify(200).to_crs(4326) if False else o3.geometry.simplify(200)
    o3 = o3.to_crs(4326).merge(t.drop(columns=["adm3_name", "adm2_name"]), on="adm3_pcode", how="left")
    keep = ["adm3_pcode", "adm3_name", "adm2_name", "hamlets_rural", "villages_rural", "q1", "q2", "q3",
            "building_coverage_q12", "pbs_settlements_2020", "villages_per_pbs_settlement", "named_share", "geometry"]
    teh = json.loads(o3[keep].to_json(drop_id=True))
    pil = reg[reg.adm3_pcode.isin(PILOT_PCODES) & reg.in_rural_population]
    pts = gpd.GeoDataFrame(pil[["vid", "name", "quality_class", "n_buildings", "settlement_class"]],
                           geometry=gpd.points_from_xy(pil.lon, pil.lat), crs=4326)
    pts["name"] = pts.name.fillna("")
    pil_json = json.loads(pts.to_json(drop_id=True))
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>VISTA-Sindh inventory v1.0 QC map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{{height:100%;margin:0}} .legend{{background:#fff;padding:6px 8px;font:12px sans-serif;line-height:18px}}
.legend i{{width:14px;height:14px;float:left;margin-right:6px;opacity:.8}}</style></head><body><div id="map"></div>
<script>
const teh = {json.dumps(teh)};
const pilots = {json.dumps(pil_json)};
const map = L.map('map').setView([25.9, 68.8], 7);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{maxZoom: 18, attribution: '&copy; OpenStreetMap'}}).addTo(map);
const esri = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{maxZoom: 18, attribution: 'Esri World Imagery'}});
function col(v){{ return v==null?'#ccc': v>=0.95?'#08519c': v>=0.9?'#3182bd': v>=0.8?'#6baed6': v>=0.6?'#bdd7e7':'#f7fbff'; }}
const tehLayer = L.geoJSON(teh, {{style: f => ({{color:'#333', weight:1, fillColor: col(f.properties.building_coverage_q12), fillOpacity:.6}}),
  onEachFeature: (f, l) => {{ const p = f.properties; l.bindPopup(`<b>${{p.adm3_name}}</b> (${{p.adm2_name}})<br>rural hamlets ${{p.hamlets_rural}} | villages ${{p.villages_rural}}<br>Q1 ${{p.q1}} Q2 ${{p.q2}} Q3 ${{p.q3}}<br>building coverage Q1-Q2: ${{p.building_coverage_q12}}<br>PBS settlements 2020: ${{p.pbs_settlements_2020}} (villages/PBS ${{p.villages_per_pbs_settlement}})<br>named share ${{p.named_share}}`); }} }}).addTo(map);
const qcol = {{Q1:'#1a9641', Q2:'#fdae61', Q3:'#d7191c'}};
const pilotLayer = L.geoJSON(pilots, {{pointToLayer: (f, ll) => L.circleMarker(ll, {{radius: 3, color: qcol[f.properties.quality_class], weight: 1, fillOpacity: .8}}),
  onEachFeature: (f, l) => l.bindPopup(`<b>${{f.properties.vid}}</b><br>${{f.properties.name}}<br>${{f.properties.quality_class}}, ${{f.properties.n_buildings}} buildings, ${{f.properties.settlement_class}}`) }});
L.control.layers({{'OpenStreetMap': map._layers[Object.keys(map._layers)[0]], 'Esri imagery': esri}}, {{'Tehsils (building coverage Q1-Q2)': tehLayer, 'Pilot hamlets (Mithi, Sanghar, Shah Bunder)': pilotLayer}}).addTo(map);
const legend = L.control({{position:'bottomright'}}); legend.onAdd = () => {{ const d = L.DomUtil.create('div','legend');
 d.innerHTML = '<b>Building coverage Q1-Q2</b><br>' + [[0.95,'&ge; 0.95'],[0.9,'0.90-0.95'],[0.8,'0.80-0.90'],[0.6,'0.60-0.80'],[0,'&lt; 0.60']].map(([v,t]) => `<i style="background:${{col(v)}}"></i>${{t}}<br>`).join('') + '<br><b>Pilot hamlets</b><br><i style="background:#1a9641"></i>Q1<br><i style="background:#fdae61"></i>Q2<br><i style="background:#d7191c"></i>Q3'; return d; }}; legend.addTo(map);
</script></body></html>"""
    MAPS.mkdir(parents=True, exist_ok=True)
    (MAPS / "interactive_map.html").write_text(html, encoding="utf-8")


def atlas(reg: gpd.GeoDataFrame) -> int:
    if not (ZV1 / "zones_resource.parquet").exists():
        print("zones/v1 missing: atlas skipped")
        return 0
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    core = gpd.read_parquet(ZV1 / "zones_core.parquet").set_index("vid").to_crs(CRS)
    res = gpd.read_parquet(ZV1 / "zones_resource.parquet").set_index("vid").to_crs(CRS)
    conn = gpd.read_parquet(ZV1 / "zones_connectivity.parquet").set_index("vid").to_crs(CRS) \
        if (ZV1 / "zones_connectivity.parquet").exists() else None
    fp = gpd.read_parquet(VI / "raw/footprints.parquet", columns=["lon", "lat", "geometry"])
    roads = gpd.read_file(ROOT / "data/raw/osm/geofabrik_pakistan_260712_shp/gis_osm_roads_free_1.shp",
                          bbox=(66.4, 23.6, 71.2, 28.6), columns=["fclass"]).to_crs(CRS)
    water = gpd.read_file(ROOT / "data/raw/osm/geofabrik_pakistan_260712_shp/gis_osm_waterways_free_1.shp",
                          bbox=(66.4, 23.6, 71.2, 28.6), columns=["fclass"]).to_crs(CRS)
    # 20 sheets: 2 per district for 10 districts spread over Sindh, Q1 hamlets, one small and one large
    rng = np.random.default_rng(24)
    districts = ["Tharparkar", "Sanghar", "Sujawal", "Badin", "Dadu", "Jacobabad", "Khairpur", "Larkana", "Umer Kot", "Thatta"]
    picks = []
    r = reg[reg.in_rural_population & (reg.quality_class == "Q1") & reg.vid.isin(res.index)]
    for d in districts:
        g = r[r.adm2_name == d]
        if g.empty:
            continue
        small = g[g.n_buildings.between(10, 40)]
        large = g[g.n_buildings >= 150]
        for sub in (small, large):
            if len(sub):
                picks.append(sub.iloc[rng.integers(len(sub))])
    MAPS.mkdir(parents=True, exist_ok=True)
    regm = reg.set_index("vid").to_crs(CRS)
    with PdfPages(MAPS / "atlas_v0.1.pdf") as pdf:
        for h in picks[:20]:
            vid = h.vid
            rz = res.loc[vid].geometry
            minx, miny, maxx, maxy = rz.bounds
            pad = 300
            win = (minx - pad, miny - pad, maxx + pad, maxy + pad)
            fig, ax = plt.subplots(figsize=(8.27, 8.27))
            box = gpd.GeoSeries([__import__("shapely").box(*win)], crs=CRS)
            rd = roads[roads.intersects(box.iloc[0])]
            wt = water[water.intersects(box.iloc[0])]
            bl = fp.cx[win[0]:win[2], win[1]:win[3]] if False else fp.to_crs(CRS).cx[win[0]:win[2], win[1]:win[3]]
            gpd.GeoSeries([rz], crs=CRS).plot(ax=ax, facecolor="#fde0a6", edgecolor="#e08214", alpha=.5, linewidth=1)
            if conn is not None and vid in conn.index and not conn.loc[vid].geometry.is_empty:
                gpd.GeoSeries([conn.loc[vid].geometry], crs=CRS).plot(ax=ax, facecolor="#b2abd2", edgecolor="#5e3c99", alpha=.6)
            neighbours = regm[regm.adm3_pcode == h.adm3_pcode]
            neighbours = neighbours[neighbours.intersects(box.iloc[0])]
            neighbours.plot(ax=ax, facecolor="#999999", edgecolor="#555555", alpha=.6, linewidth=.5)
            gpd.GeoSeries([core.loc[vid].geometry], crs=CRS).plot(ax=ax, facecolor="none", edgecolor="#d7191c", linewidth=1.5)
            gpd.GeoSeries([regm.loc[vid].geometry], crs=CRS).plot(ax=ax, facecolor="#d7191c", alpha=.5)
            if len(bl):
                bl.plot(ax=ax, markersize=1, color="k", alpha=.5)
            if len(rd):
                rd.plot(ax=ax, color="#4d4d4d", linewidth=.6)
            if len(wt):
                wt.plot(ax=ax, color="#2b8cbe", linewidth=.8)
            ax.set_xlim(win[0], win[2]); ax.set_ylim(win[1], win[3]); ax.set_aspect("equal")
            ax.set_xticks([]); ax.set_yticks([])
            name = h["name"] if isinstance(h["name"], str) else "(unnamed)"
            ax.set_title(f"{vid}\n{name} | {h.adm3_name}, {h.adm2_name} | {h.quality_class}, {int(h.n_buildings)} buildings, "
                         f"{h.settlement_class}\nred: settlement + core (100 m); orange: resource zone (r_max {res.loc[vid].r_max:.0f} m); "
                         f"purple: connectivity corridors; grey: other hamlets; dots: buildings; lines: roads / waterways", fontsize=8)
            pdf.savefig(fig); plt.close(fig)
    return len(picks[:20])


def main() -> int:
    reg = gpd.read_parquet(VI / "registry/village_registry.parquet")
    t, d = tables(reg)
    TAB.mkdir(parents=True, exist_ok=True)
    t.to_csv(TAB / "coverage_by_tehsil.csv", index=False)
    d.to_csv(TAB / "coverage_by_district.csv", index=False)
    interactive_map(t, reg)
    n = atlas(reg)
    rural = d.hamlets_rural.sum()
    print(f"districts {len(d)}, tehsils {len(t)}; rural hamlets {int(rural):,}; Q1-Q2 share {(d.q1.sum() + d.q2.sum()) / rural:.3f}; "
          f"building coverage Q1-Q2 (province) {d.buildings_q12.sum() / d.buildings_rural_all.sum():.3f}")
    print(d[["adm2_name", "hamlets_rural", "q12_share", "building_coverage_q12", "villages_per_pbs_settlement"]]
          .sort_values("building_coverage_q12").to_string(index=False))
    print(f"atlas sheets: {n}; map: {MAPS / 'interactive_map.html'} ({(MAPS / 'interactive_map.html').stat().st_size / 2**20:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
