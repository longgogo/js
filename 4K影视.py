# coding=utf-8
"""
4K影视 —— TVBox Python 蜘蛛（py 源）

站点：https://www.4kvms.org   （自建 CMS，Alpine.js + Tailwind 前端，非海洋CMS）
路由：
  首页     /
  分类     /movie  /tv  /anime                （分区首页，只有推荐位，无翻页）
  筛选     /filter?classify=1&areas=7&years=1&sort_by=update_time&order=desc&page=N
  详情     /play/{slug}                        （剧集也在这里，{slug} 为某一集的短码）
  搜索     /search?q={关键词}                  （无翻页）
  片单     /playlists  排行榜 /richlist

★ 播放地址不在 HTML 里，由 WASM（nbmovie_wasm_bg.wasm）里的 build_play_url 现算：
    GET /video/play?p={dataid}&v={slug}&q={quality}&s={签名}&t={时间戳}&k={播放键}
  逆向结论（已对拍 WASM，21/21 全中）：
    s = HMAC-SHA256(key = slug, msg = "{dataid}:{时间戳}:{slug}") 取前 32 位十六进制
    k = base64( play_key 逐字节 XOR "nbmovie2024secretkey" )
  其中
    时间戳   = 播放页 <meta id="nb-st" content="...">（服务端渲染时间，必须新鲜）
    play_key = 播放页内联 JS 的 userlink:'...'（每片不同，必须现取）
  接口返回 JSON：data.quality_urls[] = [{mtype,bitrate,title,description,isvip,locked,url}]
  4K 那一路 locked=true（VIP），取未锁的最高码率那路即可 —— 直出 m3u8，parse=0。

★ 本文件只用标准库：hashlib / base64 / re / json / urllib。
  HMAC 与 base64 均按 DRPY 环境可能缺库的情况做了手写兜底，零第三方依赖。

★ 备用域名：内置 10 个官方镜像（来自其地址发布页 4kvm.site），
  任一域名不可用会自动切换，并把当前可用域名记住，下次优先使用。
"""
import hashlib
import json
import re
import time
import urllib.parse

try:
    import base64 as _b64
except Exception:
    _b64 = None

try:
    from base.spider import Spider
except Exception:                      # 本地调试用：不依赖 TVBox 运行时
    class Spider(object):
        pass


# ---------------------------------------------------------------------------
# 纯标准库小工具（HMAC-SHA256 / base64），不依赖 hmac、base64 是否可用
# ---------------------------------------------------------------------------

SALT = "nbmovie2024secretkey"
_B64_TABLE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _b64encode(raw):
    """bytes -> str；base64 模块不可用时手写。"""
    if _b64 is not None:
        try:
            return _b64.b64encode(raw).decode("ascii")
        except Exception:
            pass
    out, i = [], 0
    n = len(raw)
    while i < n:
        chunk = raw[i:i + 3]
        pad = 3 - len(chunk)
        b = (chunk + b"\x00" * pad)
        v = (b[0] << 16) | (b[1] << 8) | b[2]
        out.append(_B64_TABLE[(v >> 18) & 63])
        out.append(_B64_TABLE[(v >> 12) & 63])
        out.append(_B64_TABLE[(v >> 6) & 63] if pad < 2 else "=")
        out.append(_B64_TABLE[v & 63] if pad < 1 else "=")
        i += 3
    return "".join(out)


def _hmac_sha256_hex(key, msg):
    """HMAC-SHA256，返回 64 位十六进制；手写实现，只用 hashlib。"""
    try:
        import hmac as _hmac
        return _hmac.new(key, msg, hashlib.sha256).hexdigest()
    except Exception:
        pass
    block = 64
    if len(key) > block:
        key = hashlib.sha256(key).digest()
    key = key + b"\x00" * (block - len(key))
    ipad = bytes(b ^ 0x36 for b in key)
    opad = bytes(b ^ 0x5C for b in key)
    return hashlib.sha256(opad + hashlib.sha256(ipad + msg).digest()).hexdigest()


def _sign(dataid, ts, slug):
    """WASM build_play_url 里的签名 s"""
    return _hmac_sha256_hex(slug.encode("utf-8"),
                            ("%s:%s:%s" % (dataid, ts, slug)).encode("utf-8"))[:32]


def _play_key_b64(userlink):
    """WASM 里的播放键 k = base64(userlink 逐字节 XOR 盐)"""
    salt = SALT.encode("utf-8")
    raw = bytes(ord(ch) ^ salt[i % len(salt)] for i, ch in enumerate(userlink))
    return _b64encode(raw)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

HOSTS = [
    "https://www.4kvms.org",
    "https://www.4kvms.com",
    "https://www.4kvm.org",
    "https://www.4kvm.com",
    "https://www.4kvm.cc",
    "https://www.4kvm.net",
    "https://www.4kvm.me",
    "https://www.4kvm.tv",
    "https://www.4kvm.pro",
    "https://www.4kvm.top",
]

# 分类：classify=1电影 2电视剧 3动漫 4综艺
# 地区：5美国 6法国 7中国 11日本 12韩国 14中国香港 21中国台湾 30英国 52中国大陆 78其他
# 年份：1=2026 3=2025 4=2024 56=2023 13=2022 2=2021 6=2020 8=2019 9=2018
# type_id 编码规则：c{classify}  或  c{classify}a{areas}  或  c{classify}y{years}
CLASSES = [
    # 说明：站点筛选页虽有 classify=4「综艺」，但其库内为空，故不列入
    ("c1", "电影"), ("c2", "电视剧"), ("c3", "动漫"),
    ("c1a52", "华语电影"), ("c1a5", "美国电影"), ("c1a11", "日本电影"),
    ("c1a12", "韩国电影"), ("c1a14", "香港电影"), ("c1a21", "台湾电影"),
    ("c2a52", "国产剧"), ("c2a5", "美剧"), ("c2a12", "韩剧"),
    ("c2a11", "日剧"), ("c2a14", "港剧"), ("c2a21", "台剧"),
    ("c3a52", "国产动漫"), ("c3a11", "日本动漫"),
    ("c1y1", "最新电影"), ("c2y1", "最新剧集"), ("c1y3", "2025电影"),
    ("c2y3", "2025剧集"), ("c1h", "热门电影"), ("c2h", "热门剧集"),
]

CARD_A = re.compile(r'<a\s+href="(/play/([A-Za-z0-9]+))"')
CARD_IMG = re.compile(r'data-src="([^"]+)"')
CARD_ALT = re.compile(r'\balt="([^"]*)"')
CARD_BADGE = re.compile(r'<span class="absolute top-2 right-2[^"]*"[^>]*>\s*(.*?)\s*</span>', re.S)
CARD_NOTE = re.compile(r'<span class="absolute bottom-0[^"]*"[^>]*>\s*(.*?)\s*</span>', re.S)

EP_A = re.compile(
    r'<a\s+href="/play/([A-Za-z0-9]+)"[^>]*?'
    r'data-line="(\d+)"\s+data-episode="(\d+)"\s+dataid="(\d+)"')
EP_A2 = re.compile(r'<a\s+href="/play/([A-Za-z0-9]+)"[^>]*?dataid="(\d+)"')
GRID = re.compile(
    r'<div class="col-span-1 text-gray-500">\s*([^<]+?)\s*</div>\s*'
    r'<div class="col-span-2[^"]*">(.*?)</div>', re.S)


# ---------------------------------------------------------------------------
# 蜘蛛主体
# ---------------------------------------------------------------------------
class Spider(Spider):

    DEFAULT_HOST = HOSTS[0]
    UA = ("Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/126.0.0.0 Mobile Safari/537.36")
    PAGE_SIZE = 24

    # ================= 基础 =================

    def getName(self):
        return "4K影视"

    def init(self, extend=""):
        host = (extend or "").strip()
        if not host:
            host = self.DEFAULT_HOST
        if not host.startswith("http"):
            host = "https://" + host
        self.host = host.rstrip("/")
        self._bad = set()

    def isVideoFormat(self, url):
        return True if re.search(r"\.(m3u8|mp4|flv)(\?|$)", url or "") else False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ================= HTTP =================

    def _raw(self, url, headers=None, timeout=20):
        """优先用运行时自带的 self.fetch，取不到再退回 urllib。"""
        h = {
            "User-Agent": self.UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if headers:
            h.update(headers)
        fetch = getattr(self, "fetch", None)
        if callable(fetch):
            for kw in ({"headers": h, "timeout": timeout}, {"headers": h}):
                try:
                    r = fetch(url, **kw)
                    if r is not None:
                        return r
                except TypeError:
                    continue
                except Exception:
                    break
        try:
            import urllib.request
            req = urllib.request.Request(url, headers=h)
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception:
            return None

    @staticmethod
    def _text(r):
        if r is None:
            return ""
        try:
            t = r.text
            if t:
                return t
        except Exception:
            pass
        try:
            raw = r.read()
        except Exception:
            return ""
        if isinstance(raw, str):
            return raw
        try:
            import gzip
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
        except Exception:
            pass
        for enc in ("utf-8", "gbk", "ignore"):
            try:
                return raw.decode("utf-8" if enc == "ignore" else enc,
                                  "ignore" if enc == "ignore" else "strict")
            except Exception:
                continue
        return ""

    def _get(self, path, referer=None, tries=2, minlen=2000):
        """path 可为 '/xxx' 或完整 URL；当前域名不通就换镜像。"""
        if path.startswith("http"):
            return self._text(self._raw(path, headers=(
                {"Referer": referer} if referer else None), timeout=12))
        order = [self.host] + [x for x in HOSTS if x != self.host]
        good = [x for x in order if x not in self._bad]
        hdr = {"Referer": referer} if referer else None
        last = ""
        for attempt in range(tries):
            # 第一轮只试已知可用域名；仍失败再把"坏域名"翻出来重试一次
            hosts = good if attempt == 0 else (good + [x for x in order if x in self._bad])
            for h in hosts:
                try:
                    t = self._text(self._raw(h + path, headers=hdr, timeout=12))
                except Exception:
                    t = ""
                if t and len(t) >= minlen:
                    if h != self.host:
                        self.host = h
                    self._bad.discard(h)
                    return t
                self._bad.add(h)          # 记住不可用，后续优先跳过
                if t:
                    last = t
            if last:
                break
            time.sleep(0.4)
        return last

    # ================= 工具 =================

    @staticmethod
    def _unesc(s):
        if not s:
            return ""
        return (s.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
                 .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
                 .replace("&#x27;", "'"))

    @staticmethod
    def _clean(s):
        return re.sub(r"\s+", " ", (s or "")).strip()

    def _cards(self, html, limit=0):
        """首页 / 筛选页 / 搜索页通用：以 <a href="/play/xxx"> 为锚点向后找封面与标题。"""
        out, seen = [], set()
        if not html:
            return out
        text = html.replace("&amp;", "&")
        anchors = list(CARD_A.finditer(text))
        for i, m in enumerate(anchors):
            slug = m.group(2)
            if slug in seen:
                continue
            nxt = anchors[i + 1].start() if i + 1 < len(anchors) else len(text)
            seg = text[m.start():min(nxt, m.start() + 2500)]
            mi = CARD_IMG.search(seg)
            if not mi:
                continue
            ma = CARD_ALT.search(seg)
            name = self._clean(self._unesc(ma.group(1))) if ma else ""
            if not name:
                continue
            mn = CARD_NOTE.search(seg)          # 底部「更新至N集」
            mb = CARD_BADGE.search(seg)          # 右上角「4k」角标
            rem = self._clean(self._unesc(mn.group(1))) if mn else ""
            if not rem and mb:
                rem = self._clean(self._unesc(mb.group(1)))
            seen.add(slug)
            out.append({
                "vod_id": slug,
                "vod_name": name,
                "vod_pic": self._unesc(mi.group(1)),
                "vod_remarks": rem,
            })
            if limit and len(out) >= limit:
                break
        return out

    # ================= 首页 / 分类 / 搜索 =================

    def homeContent(self, filter):
        return {"class": [{"type_id": t, "type_name": n} for t, n in CLASSES]}

    def homeVideoContent(self):
        return {"list": self._cards(self._get("/"))}

    @staticmethod
    def _tid_url(tid, pg):
        m = re.match(r"^c(\d+)(?:a(\d+))?(?:y(\d+))?h?$", str(tid))
        if not m:
            m = re.match(r"^c(\d+)", str(tid))
            if not m:
                return "/filter?classify=1"
        cls, area, year = m.group(1), m.group(2), m.group(3)
        q = ["classify=" + cls]
        if area:
            q.append("areas=" + area)
        if year:
            q.append("years=" + year)
        if str(tid).endswith("h"):                      # 热门
            q.append("sort_by=hits")
            q.append("order=desc")
        if pg and pg > 1:
            q.append("page=%d" % pg)
        return "/filter?" + "&".join(q)

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        html = self._get(self._tid_url(tid, pg))
        lst = self._cards(html)
        total = 0
        mt = re.search(r"共\s*(?:<[^>]*>\s*)*(\d+)\s*(?:</[^>]*>\s*)*\s*(?:个|部|条)", html)
        if mt:
            total = int(mt.group(1))
        pages = sorted(set(int(x) for x in re.findall(r"[?&]page=(\d+)", html)))
        pagecount = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE if total else (max(pages) if pages else 1)
        if not lst and pg > 1:
            pagecount = pg - 1
        return {"list": lst, "page": pg, "pagecount": pagecount,
                "limit": len(lst) or self.PAGE_SIZE, "total": total or 999999}

    def searchContent(self, key, quick, pg=1):
        key = self._clean(key)
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if not key:
            return {"list": [], "page": 1}
        if pg > 1:                                      # 站点搜索无翻页
            return {"list": [], "page": pg}
        url = "/search?q=" + urllib.parse.quote(key, safe="")
        html = self._get(url)
        return {"list": self._cards(html), "page": pg}

    # ================= 详情 =================

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = str(vid).strip()
        vid = re.sub(r"^https?://[^/]+", "", vid)
        vid = vid.strip("/").split("/")[-1].split("|")[0]
        if vid.startswith("play/"):
            vid = vid[5:]
        d = self._detail(vid)
        return {"list": [d]} if d else {"list": []}

    def _meta(self, html, name):
        m = re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content="([^"]*)"' % name, html)
        if not m:
            m = re.search(r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)=["\']%s["\']' % name, html)
        return self._unesc(m.group(1)) if m else ""

    def _grid(self, html, label):
        for m in GRID.finditer(html):
            if self._clean(m.group(1)) == label:
                return self._clean(self._unesc(re.sub(r"<[^>]+>", " ", m.group(2))))
        return ""

    def _detail(self, slug):
        html = self._get("/play/" + slug, referer=self.host + "/")
        if not html or len(html) < 3000:
            return None
        og = self._meta(html, "og:title") or self._clean(
            (re.search(r"<title>(.*?)</title>", html, re.S).group(1) if re.search(r"<title>(.*?)</title>", html, re.S) else ""))
        name = re.sub(r"\s*-\s*第\d+[集期话].*$", "", og)
        name = re.sub(r"\s*-\s*4k影视\s*$", "", name).strip() or og
        pic = self._meta(html, "og:image")
        content = self._clean(self._meta(html, "og:description") or self._meta(html, "description"))
        if not content:
            mi = re.search(r'(?s)<span class="data"[^>]*>(.*?)</span>', html)
            if mi:
                content = self._clean(self._unesc(re.sub(r"<[^>]+>", " ", mi.group(1))))

        release = self._grid(html, "上映") or self._grid(html, "首播")
        year = (re.search(r"(\d{4})", release).group(1) if release else "")
        if not year:
            kw = self._meta(html, "keywords")
            y = re.findall(r"(19|20)\d{2}", kw)
            year = y[0] if y else ""

        upd = ""
        mu = re.search(r"更新至\s*([^<，,]{1,20})", html)
        if mu:
            upd = "更新至" + self._clean(mu.group(1)).rstrip("，, ")
        badge = ""
        mb = re.search(r'<span class="absolute[^"]*"[^>]*>\s*([^<]{1,10})\s*</span>', html)
        if mb:
            badge = self._clean(mb.group(1))

        # ---- 剧集 ----
        eps = EP_A.findall(html)
        if not eps:
            eps = [("/play/" + a, "1", str(i + 1), d)
                   for i, (a, d) in enumerate(EP_A2.findall(html))]
        line_names = re.findall(r"lineName\s*:\s*'([^']*)'", html)
        buckets = {}
        order = []
        for href, line, ep, did in eps:
            if line not in buckets:
                buckets[line] = []
                order.append(line)
            try:
                no = int(ep)
            except Exception:
                no = len(buckets[line]) + 1
            buckets[line].append((no, "%s|%s" % (href.split("/")[-1], did)))
        order.sort(key=lambda x: int(x) if str(x).isdigit() else 0)
        froms, urls = [], []
        for idx, line in enumerate(order):
            nm = line_names[idx] if idx < len(line_names) and line_names[idx] else ""
            nm = nm if nm else ("线路%s" % line)
            items = sorted(buckets[line], key=lambda x: x[0])
            urls.append("#".join("第%d集$%s" % (no, u) for no, u in items))
            froms.append(nm)
        if not urls:
            did = re.search(r'dataid="(\d+)"', html)
            urls = ["第1集$%s|%s" % (slug, did.group(1) if did else "0")]
            froms = ["线路1"]

        return {
            "vod_id": slug,
            "vod_name": name,
            "vod_pic": pic,
            "vod_content": content,
            "vod_actor": self._grid(html, "主演"),
            "vod_director": self._grid(html, "导演"),
            "vod_area": self._grid(html, "地区"),
            "vod_lang": self._grid(html, "语言"),
            "vod_year": year,
            "type_name": self._grid(html, "类型"),
            "vod_remarks": upd or badge,
            "vod_play_from": "$$$".join(froms),
            "vod_play_url": "$$$".join(urls),
        }

    # ================= 播放 =================

    def playerContent(self, flag, id, vipFlags):
        parts = str(id or "").strip().split("|")
        slug = parts[0].strip("/").split("/")[-1]
        dataid = parts[1] if len(parts) > 1 and parts[1].isdigit() else ""
        if not slug:
            return {}

        referer = self.host + "/play/" + slug
        html = self._get("/play/" + slug, referer=referer)
        if not html:
            return {}
        mul = re.search(r"userlink\s*:\s*'([^']*)'", html)
        if not mul:
            mul = re.search(r'userlink\s*:\s*"([^"]*)"', html)
        ts = ""
        mst = re.search(r'id="nb-st"\s+content="(\d+)"', html)
        if not mst:
            mst = re.search(r'id="nb-st"[^>]*content="(\d+)"', html)
        if mst:
            ts = mst.group(1)
        if not ts:
            ts = str(int(time.time() * 1000))
        if not mul:
            return {"parse": 1, "url": referer, "header": {"User-Agent": self.UA, "Referer": referer}}
        if not dataid:
            md = re.search(r'dataid="(\d+)"', html)
            dataid = md.group(1) if md else ""

        k = _play_key_b64(mul.group(1))
        s = _sign(dataid, ts, slug)
        api = ("/video/play?p=%s&v=%s&q=1080&s=%s&t=%s&k=%s"
               % (dataid, slug, s, ts, urllib.parse.quote(k, safe="")))
        body = self._get(api, referer=referer, minlen=2)
        url = self._pick(body)
        if not url:
            return {"parse": 1, "url": referer, "header": {"User-Agent": self.UA, "Referer": referer}}
        result = {
            "parse": 0,
            "url": url,
            "header": {"User-Agent": self.UA, "Referer": referer,
                       "X-Requested-With": "XMLHttpRequest"},
        }
        try:
            d = json.loads(body)
            sub = ((d.get("data") or {}).get("subtitle_url") or "")
            if sub.startswith("http"):
                result["subt"] = sub
        except Exception:
            pass
        return result

    def _pick(self, body):
        """从 /video/play 的 JSON 里挑一条未上锁、码率最高的直链。"""
        if not body:
            return ""
        m = re.search(r'"url"\s*:\s*"(https?://[^"]+)"', body)
        direct = self._unesc(m.group(1)) if m else ""
        try:
            d = json.loads(body)
        except Exception:
            return direct
        data = d.get("data") or {}
        best, best_rate = "", -1
        for q in (data.get("quality_urls") or []):
            if q.get("locked") or q.get("isvip"):
                continue
            u = str(q.get("url") or "")
            if not u.startswith("http"):
                continue
            try:
                rate = int(q.get("bitrate") or 0)
            except Exception:
                rate = 0
            if rate >= best_rate:
                best, best_rate = u, rate
        return best or direct

    # ================= 本地代理（直链，无需代理） =================

    def localProxy(self, param):
        return None
