# coding=utf-8
# !/usr/bin/python
# HDmoli（高清影视）TVBox Python 蜘蛛
# 站点：MacCMS + mytheme(米酷 myui) 主题，自定义伪静态
#   分类   /mlist/index{tid}.html            tid: 1电影 2剧集 3纪录片 4动画 5综艺
#   翻页   /show/{tid}--------{pg}---.html   （48 条/页，真分页）
#   详情   /movie/index{id}.html
#   播放   /play/{id}-{sid}-{nid}.html
#   搜索   /search/-------------.html?wd={关键词}   （UTF-8）
# 播放链路：player_aaaa.encrypt=3 + hex→base64 密文 →
#   /static/player/{from}.js → /static/player/artplayer/?url={密文} →
#   智能线走第三方接口 POST hd.ticktockwow.com/smartplay-cache/api/webvideo_ty.php
#   （Origin/Referer 必带），返回密文 → AES-CBC 解密出直链。
#   密钥推导：key = MD5(timestamp + "RY7e48naFXPsLJC")[16:32]
#             iv  = MD5(timestamp + "RY7e48naFXPsLJC")[0:16]
#   signature = MD5(当前unix秒)
import re
import json
import time
import hashlib
import base64
import urllib.parse

from base.spider import Spider


# ----------------------------------------------------------------------------
# 纯 Python AES-128-CBC 解密（零依赖，S 盒按算法现算，避免手抄出错）
# ----------------------------------------------------------------------------
def _gf_mul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return r


def _gf_inv(a):
    if a == 0:
        return 0
    for x in range(1, 256):
        if _gf_mul(a, x) == 1:
            return x
    return 0


def _rotl8(x, n):
    return ((x << n) | (x >> (8 - n))) & 0xFF


def _build_tables():
    sbox = []
    for i in range(256):
        inv = _gf_inv(i)
        sbox.append(inv ^ _rotl8(inv, 1) ^ _rotl8(inv, 2) ^ _rotl8(inv, 3) ^ _rotl8(inv, 4) ^ 0x63)
    inv_sbox = [0] * 256
    for i, v in enumerate(sbox):
        inv_sbox[v] = i
    return sbox, inv_sbox


_SBOX, _INV_SBOX = _build_tables()
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _expand_key(key):
    assert len(key) == 16
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    rks = []
    for r in range(11):
        rk = []
        for c in range(4):
            rk.extend(w[r * 4 + c])
        rks.append(rk)
    return rks


def _decrypt_block(block, rks):
    s = list(block)

    def inv_shift_rows(x):
        out = list(x)
        for r in range(1, 4):
            row = [x[r + 4 * c] for c in range(4)]
            row = row[-r:] + row[:-r]
            for c in range(4):
                out[r + 4 * c] = row[c]
        return out

    def inv_mix_columns(x):
        out = list(x)
        for c in range(4):
            a = [x[4 * c + r] for r in range(4)]
            out[4 * c + 0] = _gf_mul(a[0], 14) ^ _gf_mul(a[1], 11) ^ _gf_mul(a[2], 13) ^ _gf_mul(a[3], 9)
            out[4 * c + 1] = _gf_mul(a[0], 9) ^ _gf_mul(a[1], 14) ^ _gf_mul(a[2], 11) ^ _gf_mul(a[3], 13)
            out[4 * c + 2] = _gf_mul(a[0], 13) ^ _gf_mul(a[1], 9) ^ _gf_mul(a[2], 14) ^ _gf_mul(a[3], 11)
            out[4 * c + 3] = _gf_mul(a[0], 11) ^ _gf_mul(a[1], 13) ^ _gf_mul(a[2], 9) ^ _gf_mul(a[3], 14)
        return out

    def add_rk(x, rk):
        return [x[i] ^ rk[i] for i in range(16)]

    s = add_rk(s, rks[10])
    for rnd in range(9, 0, -1):
        s = inv_shift_rows(s)
        s = [_INV_SBOX[b] for b in s]
        s = add_rk(s, rks[rnd])
        s = inv_mix_columns(s)
    s = inv_shift_rows(s)
    s = [_INV_SBOX[b] for b in s]
    s = add_rk(s, rks[0])
    return bytes(s)


def _aes_cbc_decrypt(key, iv, data):
    rks = _expand_key(key)
    prev = iv
    out = b""
    for i in range(0, len(data) - len(data) % 16, 16):
        blk = data[i:i + 16]
        dec = _decrypt_block(blk, rks)
        out += bytes(dec[j] ^ prev[j] for j in range(16))
        prev = blk
    return out


def _pkcs7_unpad(data):
    if not data:
        return data
    n = data[-1]
    if 1 <= n <= 16 and data[-n:] == bytes([n]) * n:
        return data[:-n]
    return data


def hdmoli_decrypt(cipher_b64, timestamp):
    """站点播放密文 -> 明文明文地址。"""
    h = hashlib.md5((str(timestamp) + "RY7e48naFXPsLJC").encode("utf-8")).hexdigest()
    key = h[16:32].encode("utf-8")
    iv = h[0:16].encode("utf-8")
    raw = base64.b64decode(cipher_b64 + "=" * (-len(cipher_b64) % 4))
    return _pkcs7_unpad(_aes_cbc_decrypt(key, iv, raw)).decode("utf-8", "ignore")


# ----------------------------------------------------------------------------
# 蜘蛛主体
# ----------------------------------------------------------------------------
class Spider(Spider):

    SALT = "RY7e48naFXPsLJC"
    SMART_API = "https://hd.ticktockwow.com/smartplay-cache/api/webvideo_ty.php"
    PAN_KW = ("网盘", "云盘", "夸克", "百度", "迅雷", "磁力", "UC", "115", "aliyun", "阿里", "pikpak", "天翼")

    def getName(self):
        return "HDmoli高清影视"

    def init(self, extend=""):
        self.host = "https://www.hdmoli.me"
        if extend:
            try:
                cfg = json.loads(extend)
                if isinstance(cfg, dict):
                    self.host = cfg.get("host") or cfg.get("url") or self.host
                elif isinstance(cfg, str) and cfg.startswith("http"):
                    self.host = cfg
            except Exception:
                if isinstance(extend, str) and extend.strip().startswith("http"):
                    self.host = extend.strip()
        self.host = self.host.rstrip("/")

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ---------------- 基础请求 ----------------
    def _hdr(self, extra=None):
        h = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.host + "/",
        }
        if extra:
            h.update(extra)
        return h

    def _req(self, url, headers=None, timeout=15, allow_redirects=True):
        h = self._hdr(headers)
        for kw in ({"headers": h, "timeout": timeout, "allow_redirects": allow_redirects},
                   {"headers": h, "timeout": timeout},
                   {"headers": h}):
            try:
                return self.fetch(url, **kw)
            except TypeError:
                continue
            except Exception:
                return None
        return None

    def _get(self, url):
        r = self._req(url)
        try:
            return r.text if r is not None else ""
        except Exception:
            try:
                return r.content.decode("utf-8", "ignore")
            except Exception:
                return ""

    def _post(self, url, data, headers=None):
        """POST JSON。不同 TVBox 版本的 fetch 签名不一，逐个试，只认拿到 url 的那次；
        最后用标准库兜底（本地离线实测走的就是这条）。"""
        body = json.dumps(data).encode("utf-8")
        h = self._hdr(headers)
        h["Content-Type"] = "application/json"
        for kw in ({"headers": h, "data": body, "timeout": 15},
                   {"headers": h, "data": body},
                   {"headers": h, "body": body},
                   {"headers": h, "data": json.dumps(data)},
                   {"headers": h, "json": data},
                   {"headers": h, "data": body, "method": "POST"}):
            try:
                r = self.fetch(url, **kw)
            except TypeError:
                continue          # 宿主不收这个参数（TypeError 发生在发请求之前，不会重复请求）
            except Exception:
                break
            txt = ""
            try:
                txt = r.text if r is not None else ""
            except Exception:
                txt = ""
            if txt and '"url"' in txt:
                return txt
        try:
            import urllib.request as _u
            req = _u.Request(url, data=body, headers=h)
            return _u.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
        except Exception:
            return ""

    # ---------------- 列表解析 ----------------
    def _cards(self, html):
        if not html:
            return []
        html = re.sub(r"<!--.*?-->", "", html, flags=re.S)   # 去注释（pic-text 有注释干扰）
        # 首页/分类页用 myui-vodlist__box；搜索页用 myui-vodlist__media（两种卡片样式）
        blocks = re.findall(r'(?s)<div class="myui-vodlist__box">(.*?)</li>', html)
        if not blocks:
            mm = re.search(r'(?s)<ul[^>]*class="[^"]*myui-vodlist__media[^"]*"[^>]*>(.*?)</ul>', html)
            if mm:
                blocks = re.findall(r'(?s)<li class="clearfix">(.*?)</li>', mm.group(1))
        out = []
        seen = set()
        for blk in blocks:
            mh = re.search(r'href="(/movie/index(\d+)\.html)"', blk)
            mt = re.search(r'title="([^"]*)"', blk)
            if not mh or not mt:
                continue
            vid = mh.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            mp = re.search(r'data-original="([^"]*)"', blk)
            mr = re.search(r'class="pic-text[^"]*">(.*?)</span>', blk, re.S)
            out.append({
                "vod_id": vid,
                "vod_name": mt.group(1).strip(),
                "vod_pic": (mp.group(1).replace("&amp;", "&") if mp else ""),
                "vod_remarks": re.sub(r"\s+", " ", mr.group(1)).strip() if mr else "",
            })
        return out

    # ---------------- 五个数据接口 ----------------
    def homeContent(self, filter):
        classes = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "剧集"},
            {"type_id": "3", "type_name": "纪录片"},
            {"type_id": "4", "type_name": "动画"},
            {"type_id": "5", "type_name": "综艺"},
        ]
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        html = self._get(self.host + "/")
        return {"list": self._cards(html)[:50]}

    def categoryContent(self, tid, pg, filter, extend):
        url = "%s/show/%s--------%s---.html" % (self.host, tid, pg)
        html = self._get(url)
        return {"list": self._cards(html), "page": pg, "pagecount": 9999, "limit": 90, "total": 999999}

    def searchContent(self, key, quick, pg=1):
        if not key or str(pg) != "1":
            return {"list": [], "page": pg}
        url = "%s/search/-------------.html?wd=%s" % (self.host, urllib.parse.quote(key))
        return {"list": self._cards(self._get(url)), "page": pg}

    # ---------------- 详情 ----------------
    def _txt(self, s):
        s = re.sub(r"<br\s*/?>", "\n", s)
        s = re.sub(r"<[^>]+>", "", s)
        s = s.replace("&nbsp;", " ").replace("&amp;", "&")
        return re.sub(r"[ \t\r\f\v]+", " ", s).strip()

    def detailContent(self, ids):
        vid = ids[0]
        m = re.search(r"(\d+)", str(vid))
        vid = m.group(1) if m else str(vid)
        html = self._get("%s/movie/index%s.html" % (self.host, vid))
        if not html:
            return {"list": []}

        name = ""
        mh = re.search(r'(?s)<h1[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h1>', html)
        if mh:
            name = self._txt(mh.group(1))
        mp = re.search(r'(?s)class="myui-content__thumb".*?data-original="([^"]*)"', html)
        pic = mp.group(1) if mp else ""

        def field(label, end=r"</p>"):
            mm = re.search(label + r"[：:]\s*(.*?)" + end, html, re.S)
            return self._txt(mm.group(1)) if mm else ""

        area = field("地区", r"\s*(?:语言|年份|又名|分类)")
        year = field("年份", r"\s*(?:又名|语言|地区|分类)")
        tname = field("分类", r"\s*(?:地区|年份)")
        actor = field("演员")
        director = field("导演")
        intro = field("剧情简介")

        # 线路 ↔ 剧集（按 #playlistN 一一对应）
        tabs = re.findall(r'<a[^>]*href="#playlist(\d+)"[^>]*>\s*([^<]*?)\s*</a>', html)
        blocks = dict(re.findall(
            r'(?s)<div id="playlist(\d+)"[^>]*>.*?<ul class="myui-content__list[^"]*"[^>]*>(.*?)</ul>', html))
        froms, urls = [], []
        for idx, lname in tabs:
            if not lname or lname in ("同类型", "下载"):
                continue
            inner = blocks.get(idx, "")
            eps = re.findall(r'href="(/play/[^"]+)"[^>]*>([^<]*)<', inner)
            if not eps:
                continue
            froms.append(lname)
            urls.append("#".join("%s$%s" % (t.strip(), h) for h, t in eps))

        # 剔除播不了的网盘线路（整部只有网盘时再保留）
        keep_f, keep_u = [], []
        for f, u in zip(froms, urls):
            if any(k.lower() in f.lower() for k in self.PAN_KW):
                continue
            keep_f.append(f)
            keep_u.append(u)
        if keep_f:
            froms, urls = keep_f, keep_u

        video = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "type_name": tname,
            "vod_year": year,
            "vod_area": area,
            "vod_actor": actor,
            "vod_director": director,
            "vod_content": intro,
            "vod_play_from": "$$$".join(froms),
            "vod_play_url": "$$$".join(urls),
        }
        return {"list": [video]}

    # ---------------- 播放 ----------------
    def playerContent(self, flag, id, vipFlags):
        url = id
        if url.startswith("/"):
            url = self.host + url

        # 网盘直链（明文）：原样返回，播不了但保证不错位
        if re.search(r"(drive\.uc\.cn|pan\.quark\.cn|pan\.baidu\.com|115\.com|aliyundrive|alipan|pan\.xunlei)", url):
            return {"parse": 0, "url": url, "header": self._hdr()}

        html = self._get(url)
        m = re.search(r"player_aaaa\s*=\s*(\{.*?\})\s*(?:</script>|;)", html, re.S)
        if m:
            try:
                cfg = json.loads(m.group(1))
            except Exception:
                cfg = {}
            play_url = str(cfg.get("url", ""))
            fromc = str(cfg.get("from", ""))
            if re.match(r"https?://", play_url):
                return {"parse": 0, "url": play_url, "header": self._hdr()}
            if play_url and fromc:
                real = self._resolve_art(play_url)
                if real:
                    return {"parse": 0, "url": real, "header": self._hdr()}

        # 兜底：回播放页，交给 TVBox 嗅探
        return {"parse": 1, "url": url, "header": self._hdr()}

    def _resolve_art(self, cipher):
        """hex(密文) -> artplayer 页 -> 智能接口 -> AES 解密直链。"""
        art = self._get("%s/static/player/artplayer/?url=%s" % (self.host, cipher))
        if not art:
            return ""
        g = lambda n: (lambda mm: mm.group(1) if mm and mm.group(1) is not None else
                       (mm.group(2) if mm else ""))(
            re.search(r'const\s+%s\s*=\s*(?:"([^"]*)"|([A-Za-z0-9_.$]+))' % n, art))
        ppu, code, ts = g("playPageUrl"), g("secretKeySeed"), g("timestamp")
        smart = re.search(r"const\s+isSmartPlay\s*=\s*(\w+)", art)
        smart = (smart.group(1) == "true") if smart else False
        qualities = g("qualities")

        if ts and smart and ppu:
            t = str(int(time.time()))
            resp = self._post(self.SMART_API, {
                "vkey": ppu, "code": code, "t": t,
                "signature": hashlib.md5(t.encode("utf-8")).hexdigest(),
            }, {"Origin": self.host})
            try:
                j = json.loads(resp)
                if j.get("url"):
                    return hdmoli_decrypt(j["url"], ts)
            except Exception:
                pass
        # 直给型：qualities 里就是密文
        if ts and qualities and qualities.startswith("["):
            try:
                arr = json.loads(qualities)
                if arr and isinstance(arr[0], str):
                    return hdmoli_decrypt(arr[0], ts)
            except Exception:
                pass
        return ""
