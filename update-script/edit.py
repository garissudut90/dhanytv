#!/usr/bin/env python3
"""
edit.py - bangun playlist.m3u dari dhanytv.m3u (sumber utama) + channel pilihan
dari playlist lain (EXTRA_SOURCES), dalam format ramah TiviMate.

Pemakaian:
    python3 edit.py dhanytv.m3u playlist.m3u

Yang dilakukan secara default:
  1. Baris #KODIPROP lisensi (license_type, license_key, manifest_type) dipindah
     ke SETELAH #EXTINF, supaya DASH/ClearKey tetap ada dan urutannya rapi.
  2. #EXTVLCOPT referrer/origin/user-agent diubah jadi header di ujung URL:
     URL|Referer=...&Origin=...&User-Agent=...
  3. Baris #EXTHTTP dan baris tambahan lain dibuang.
  4. Channel pilihan dari EXTRA_SOURCES digabung ke playlist.
  5. Filter, rename, dan urutan grup/channel sesuai pengaturan di bawah.
"""
import os
import re
import sys

# ====================== PENGATURAN (edit di sini) ======================

# --- Playlist tambahan yang digabung --------------------------------------
# Satu blok per sumber. File-nya diunduh oleh workflow (lihat sync.yml).
#   "file"     : nama file hasil unduhan di repo
#   "groups"   : ambil SEMUA channel dari grup-grup ini (nama grup di sumber itu)
#   "channels" : ambil channel dengan nama ini (dicocokkan sama seperti
#                CHANNEL_ORDER: tanpa spasi/simbol/besar-kecil, tanpa "HD")
#   "put_in"   : (opsional) masukkan semua hasilnya ke grup ini di playlist Anda
#                (isi dengan nama grup yang sudah ada, atau nama baru)
# Kalau "groups" dan "channels" sama-sama kosong, tidak ada yang diambil.
#
# Contoh:
# EXTRA_SOURCES = [
#     {
#         "file": "extra1.m3u",
#         "groups" : ["ShareExt@Relax", "SHAREEXT@ MPD || SPORTS"],
#         "channels": ["TV9 NUSANTARA", "JITV HD", "DaaiTV_HD"],
#         "put_in": "Indonesia Channels",
#     },
# ]
EXTRA_SOURCES = [
    {
        "file": "update-script/extra1.m3u",
        "groups" : ["ShareExt@Relax"],
        "channels": [],
        "put_in": "Sports",
    }
]

# True = kalau channel dari sumber tambahan punya URL yang sama persis dengan
# yang sudah ada di sumber utama, lewati (tidak dobel).
SKIP_DUPLICATE_URLS = True

# --- Filter sumber utama ---------------------------------------------------
# Kalau tidak kosong, HANYA grup ini yang dipakai (huruf besar/kecil diabaikan).
# Contoh: INCLUDE_GROUPS = ["Indonesia Channels", "TVRI"]
INCLUDE_GROUPS = []

# Grup yang dibuang. Contoh: EXCLUDE_GROUPS = ["Italy Channels", "Saudi Arabia"]
EXCLUDE_GROUPS = ["Italy Channels", "Saudi Arabia", "Brunei", "China", "Internet Radio", "India", "Korea", "Japan", "Russia", "Colombia", "Argentina", "Mexico", "Brazil", "Italy", "Spain", "France", "Germany", "Kenya", "South Africa", "Nigeria", "Egypt", "Thailand", "Philippines", "Vietnam", "Turkey", "Bangladesh", "UAE & Arab", "International", "Iran", "Pakistan", "United Kingdom"]

# Ganti nama grup (berlaku untuk semua sumber, termasuk tambahan).
# Contoh: RENAME_GROUPS = {"Indonesia Channels": "Indonesia"}
RENAME_GROUPS = {"Nasional": "Indonesia Channels", "News Channel": "News", "Sports Channels": "Sports", "Sports Indo": "Sports"}

# True = buang channel Widevine (biasanya tidak jalan di TiviMate).
DROP_WIDEVINE = False

# True = buang channel DASH/DRM sama sekali (sisakan HLS biasa).
DROP_DASH = False

# --- Urutan -----------------------------------------------------------------
# Urutan grup. Grup yang disebut tampil paling atas sesuai urutan ini,
# sisanya menyusul dengan urutan aslinya. Pakai nama grup SETELAH di-rename.
# Contoh: GROUP_ORDER = ["Indonesia Channels", "TVRI", "Sports"]
GROUP_ORDER = [
    "Indonesia Channels", "Sports", "Kids", "Premium Movies", "Indonesian Entertainment & Movies",
    "Entertainment", "Entertainment & LifeStyle", "News", "Knowledge and Documentary", "HBO Group"
]

# Urutan channel DI DALAM grup. Channel yang disebut tampil paling atas sesuai
# urutan yang Anda tulis; channel lain di grup itu menyusul dengan urutan aslinya.
# Nama dicocokkan tanpa spasi/simbol/huruf besar-kecil dan tanpa akhiran "HD",
# atau bisa juga memakai tvg-id (tanpa ".id"). Contoh: "RCTI" cocok dengan
# "RCTI HD", "MNCTV" cocok dengan "MNC TV HD". Nama harus lengkap: "MNC" saja
# tidak cocok. Kalau ada channel dobel dengan nama sama, semuanya ikut pindah.
# Contoh:
# CHANNEL_ORDER = {
#     "Indonesia Channels": ["RCTI", "MNCTV", "GTV", "iNews", "SCTV", "Indosiar", "Trans7"],
# }
CHANNEL_ORDER = {
    "Indonesia Channels": ["RCTI", "MNCTV", "GTV", "iNews", "SCTV", "Indosiar", "Trans7", "Trans", "ANTV", "METRO", "TVONE"],
    "Sports": ["beIN Sports 1", "beIN Sports 2", "beIN Sports 3", "SpoTV", "Soccer Channel"],
}

# True = urutkan sisa grup (yang tidak ada di GROUP_ORDER) sesuai abjad.
SORT_REMAINING_GROUPS = False

# True = urutkan sisa channel di tiap grup sesuai abjad.
SORT_CHANNELS_AZ = False

# =======================================================================

GROUP_RE = re.compile(r'group-title="([^"]*)"')
TVGID_RE = re.compile(r'tvg-id="([^"]*)"')
LICENSE_PREFIXES = (
    "#KODIPROP:inputstream.adaptive.license_type",
    "#KODIPROP:inputstream.adaptive.license_key",
    "#KODIPROP:inputstream.adaptive.manifest_type",
)


def lower_set(items):
    return {x.strip().lower() for x in items}


INCLUDE = lower_set(INCLUDE_GROUPS)
EXCLUDE = lower_set(EXCLUDE_GROUPS)
RENAME = {k.strip().lower(): v for k, v in RENAME_GROUPS.items()}


def norm(text):
    """Samakan nama: huruf kecil, hanya huruf/angka, tanpa akhiran 'hd'/'.id'."""
    t = re.sub(r"\.id(@.*)?$", "", text.strip(), flags=re.I)
    t = re.sub(r"[^a-z0-9]", "", t.lower())
    return t[:-2] if t.endswith("hd") and len(t) > 2 else t


def parse(path):
    """Baca file M3U, kembalikan list (extinf, props, url).

    Baris # sebelum atau sesudah #EXTINF dianggap milik channel itu. Baris
    komentar (##...) dan URL yang di-comment ikut terbuang sebagai props.
    """
    with open(path, encoding="utf-8", errors="ignore") as f:
        lines = f.read().replace("\r", "").split("\n")

    items = []
    pending = []   # baris # sebelum #EXTINF berikutnya
    typo = re.compile(r"(?<=\s)(?:gr|g)group-title=")
    cur = None     # {'extinf': ..., 'props': [...]}
    for raw in lines:
        line = raw.strip()
        if line.startswith("#EXTINF"):
            line = typo.sub("group-title=", line)   # perbaiki salah ketik di sumber
            if cur:                     # #EXTINF sebelumnya tanpa URL
                pending = cur["props"] + pending
            cur = {"extinf": line, "props": []}
        elif line.startswith("#EXTM3U"):
            continue
        elif line.startswith("#"):
            (cur["props"] if cur else pending).append(line)
        elif line and cur:
            items.append((cur["extinf"], pending + cur["props"], line))
            cur, pending = None, []
    return items


def header_value(props, names):
    for p in props:
        m = re.match(r"#EXTVLCOPT:(%s)=(.*)" % names, p, re.I)
        if m:
            return m.group(2).strip().strip('"')
    return None


def info(extinf):
    m = GROUP_RE.search(extinf)
    group = m.group(1) if m else ""
    name = extinf.rsplit(",", 1)[-1].strip()
    t = TVGID_RE.search(extinf)
    return group, name, (t.group(1) if t else "")


def build_entry(extinf, props, url, main_filters=True, put_in=None):
    """Kembalikan (grup, nama, baris, tvg-id) atau None kalau dibuang."""
    group, name, tid = info(extinf)

    if main_filters:
        if INCLUDE and group.strip().lower() not in INCLUDE:
            return None
        if group.strip().lower() in EXCLUDE:
            return None

    lic = [p for p in props if p.startswith(LICENSE_PREFIXES)]
    is_dash = ".mpd" in url.lower() or any("license_key" in p for p in lic)
    is_widevine = any("widevine" in p.lower() for p in lic)
    if DROP_DASH and is_dash:
        return None
    if DROP_WIDEVINE and is_widevine:
        return None

    final_group = put_in or group
    final_group = RENAME.get(final_group.strip().lower(), final_group)
    if final_group != group:
        if GROUP_RE.search(extinf):
            extinf = GROUP_RE.sub('group-title="%s"' % final_group, extinf, count=1)
        else:
            extinf = extinf.replace("#EXTINF:-1", '#EXTINF:-1 group-title="%s"' % final_group, 1)

    if "|" not in url:
        headers = []
        ref = header_value(props, "http-referrer|http-referer")
        org = header_value(props, "http-origin")
        ua = header_value(props, "http-user-agent")
        if ref:
            headers.append("Referer=" + ref)
        if org:
            headers.append("Origin=" + org)
        if ua:
            headers.append("User-Agent=" + ua)
        if headers:
            url += "|" + "&".join(headers)

    return final_group, name, [extinf] + list(dict.fromkeys(lic)) + [url], tid


def reorder(entries):
    """Urutkan grup dan channel sesuai pengaturan; urutan asli dijaga."""
    chan_order = {g.strip().lower(): [norm(n) for n in names_]
                  for g, names_ in CHANNEL_ORDER.items()}
    order = {g.strip().lower(): i for i, g in enumerate(GROUP_ORDER)}

    groups = {}  # nama grup -> list entri, urutan kemunculan terjaga
    for e in entries:
        groups.setdefault(e[0], []).append(e)

    names = list(groups)
    listed = sorted((g for g in names if g.strip().lower() in order),
                    key=lambda g: order[g.strip().lower()])
    rest = [g for g in names if g.strip().lower() not in order]
    if SORT_REMAINING_GROUPS:
        rest.sort(key=str.lower)

    result = []
    for g in listed + rest:
        items = groups[g]
        if SORT_CHANNELS_AZ:
            items = sorted(items, key=lambda e: e[1].lower())
        wanted = chan_order.get(g.strip().lower())
        if wanted:
            pos = {n: i for i, n in enumerate(wanted)}

            def rank(e):
                keys = {norm(e[1]), norm(e[3])}
                hits = [pos[k] for k in keys if k in pos]
                return min(hits) if hits else len(pos)

            # sorted() stabil: yang tidak disebut tetap di urutan semula
            items = sorted(items, key=rank)
        result.extend(items)
    return result


def main(src, dst):
    entries = []
    seen_urls = set()
    total = kept = 0

    for extinf, props, url in parse(src):
        total += 1
        e = build_entry(extinf, props, url)
        if e:
            entries.append(e)
            seen_urls.add(url.split("|")[0])
            kept += 1

    base = os.path.dirname(os.path.abspath(src))
    for cfg in EXTRA_SOURCES:
        path = cfg.get("file", "")
        if not os.path.isabs(path):
            path = os.path.join(base, path)
        if not os.path.exists(path):
            print("Lewati (file tidak ada): %s" % cfg.get("file"))
            continue
        want_groups = lower_set(cfg.get("groups", []))
        want_names = {norm(n) for n in cfg.get("channels", [])}
        added = 0
        for extinf, props, url in parse(path):
            group, name, tid = info(extinf)
            if not (group.strip().lower() in want_groups or norm(name) in want_names):
                continue
            if SKIP_DUPLICATE_URLS and url.split("|")[0] in seen_urls:
                continue
            e = build_entry(extinf, props, url, main_filters=False,
                            put_in=cfg.get("put_in"))
            if e:
                entries.append(e)
                seen_urls.add(url.split("|")[0])
                added += 1
        print("Tambahan dari %s: %d channel" % (cfg.get("file"), added))
        kept += added

    out = ["#EXTM3U"]
    for _, _, lines_, _ in reorder(entries):
        out.extend(lines_)

    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("Selesai: %d channel ditulis ke %s (sumber utama: %d)" % (kept, dst, total))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Pemakaian: python3 edit.py <sumber.m3u> <hasil.m3u>")
    main(sys.argv[1], sys.argv[2])
