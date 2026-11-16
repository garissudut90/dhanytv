#!/usr/bin/env python3
"""
edit.py - bangun playlist.m3u dari dhanytv.m3u (sumber) dengan format ramah TiviMate.

Pemakaian:
    python3 edit.py dhanytv.m3u playlist.m3u

Yang dilakukan secara default:
  1. Baris #KODIPROP lisensi (license_type, license_key, manifest_type) dipindah
     ke SETELAH #EXTINF, supaya DASH/ClearKey tetap ada dan urutannya rapi.
  2. #EXTVLCOPT referrer/origin/user-agent diubah jadi header di ujung URL:
     URL|Referer=...&Origin=...&User-Agent=...
  3. Baris #EXTHTTP dan baris tambahan lain dibuang.
  4. Filter dan rename grup sesuai pengaturan di bawah.
"""
import re
import sys

# ====================== PENGATURAN (edit di sini) ======================

# Kalau tidak kosong, HANYA grup ini yang dipakai (huruf besar/kecil diabaikan).
# Contoh: INCLUDE_GROUPS = ["Indonesia Channels", "TVRI"]
INCLUDE_GROUPS = []

# Grup yang dibuang. Contoh: EXCLUDE_GROUPS = ["Italy Channels", "Saudi Arabia"]
EXCLUDE_GROUPS = []

# Ganti nama grup. Contoh: RENAME_GROUPS = {"Indonesia Channels": "Indonesia"}
RENAME_GROUPS = {}

# True = buang channel Widevine (biasanya tidak jalan di TiviMate).
DROP_WIDEVINE = False

# True = buang channel DASH/DRM sama sekali (sisakan HLS biasa).
DROP_DASH = False

# =======================================================================

GROUP_RE = re.compile(r'group-title="([^"]*)"')
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


def header_value(props, names):
    for p in props:
        m = re.match(r"#EXTVLCOPT:(%s)=(.*)" % names, p, re.I)
        if m:
            return m.group(2).strip().strip('"')
    return None


def build_entry(extinf, props, url):
    """Kembalikan list baris untuk satu channel, atau None kalau dibuang."""
    m = GROUP_RE.search(extinf)
    group = m.group(1) if m else ""

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

    new_group = RENAME.get(group.strip().lower())
    if new_group is not None:
        extinf = GROUP_RE.sub('group-title="%s"' % new_group, extinf, count=1)

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

    return [extinf] + list(dict.fromkeys(lic)) + [url]


def main(src, dst):
    with open(src, encoding="utf-8", errors="ignore") as f:
        lines = f.read().replace("\r", "").split("\n")

    out = ["#EXTM3U"]
    pending = []      # baris # sebelum #EXTINF (milik entri berikutnya)
    cur = None        # {'extinf': ..., 'props': [...]}
    total = kept = 0

    for raw in lines:
        line = raw.strip()
        if line.startswith("#EXTINF"):
            cur = {"extinf": line, "props": []}
        elif line.startswith("#EXTM3U"):
            continue
        elif line.startswith("#"):
            (cur["props"] if cur else pending).append(line)
        elif line and cur:
            total += 1
            entry = build_entry(cur["extinf"], pending + cur["props"], line)
            if entry:
                out.extend(entry)
                kept += 1
            cur, pending = None, []

    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("Selesai: %d dari %d channel ditulis ke %s" % (kept, total, dst))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Pemakaian: python3 edit.py <sumber.m3u> <hasil.m3u>")
    main(sys.argv[1], sys.argv[2])
