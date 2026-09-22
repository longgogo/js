# coding=utf-8
# !/usr/bin/python
# PPnix（www.ppnix.com）TVBox Python 蜘蛛
# 站点：帝国CMS(/e/)+自研英文影视模板；/cn/ 为简体中文版（标题/简介均为中文）
"""
挂载（TVBox 配置 sites 里，或作为 py 源单独加载）：
{"key":"ppnix","name":"PPnix影视","type":3,"api":"PPnix影视ppnix.py",
 "searchable":1,"quickSearch":1,"filterable":1}

特点：
 - 分类：/cn/movie/ 、/cn/tv/
 - 列表：/{type}/{类型}-{国家}-{年代}-{页码-1}-{排序}.html   24 条/页，真分页
 - 搜索：/cn/search/{关键词}-{页码-1}-.html
 - 详情：/{type}/{id}.html ，剧集藏在页面内联变量 m3u8=['1','2',...] 里
 - 播放：直链 HLS —— /info/m3u8/{id}/{集}.m3u8 （IPFS 分片，AES-128 加密）
         无需解析接口，playerContent 直接 parse=0 出直链
"""
import sys
import re
import json
import base64
import urllib.parse

sys.path.append("..")
from base.spider import Spider


class Spider(Spider):

    # ==================== 可调项 ====================
    HOST = "https://www.ppnix.com"
    LANG = "/cn"          # 简体中文（改 "" 走英文版，改 "/tw" 走繁体）
    UA = ("Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
    PER_PAGE = 24
    # 站点 m3u8 的 AES key 文件是 32 字节（=16 字节密钥的 hex 文本），
    # ffmpeg/IJK/VLC/hls.js 都只取前 16 字节，能正常解密；
    # 个别以 ExoPlayer 为内核的播放器会把 32 字节当 AES-256 → 花屏。
    # 若你的内核是 ExoPlayer，把下面改成 True，走本地代理把 key 裁成 16 字节再喂给播放器。
    USE_PROXY = False
    # ===============================================

    _ENTS = (("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'"),
             ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " "), ("&hellip;", "…"),
             ("&mdash;", "—"), ("&amp;", "&"))

    def getName(self):
        return "PPnix影视"

    def init(self, extend=""):
        self._cache = {}
        try:
            self.extend = json.loads(extend) if extend and extend.strip().startswith("{") else {}
        except Exception:
            self.extend = {}

    def isVideoFormat(self, url):
        u = url or ""
        return (".m3u8" in u) or (".mp4" in u)

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ---------------------------------------------------------------- 网络
    def _hdr(self, ref=None):
        h = {
            "User-Agent": self.UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if ref:
            h["Referer"] = ref
        return h

    def _fetch(self, url, ref=None):
        h = self._hdr(ref)
        for kw in ({"headers": h, "timeout": 20}, {"headers": h}, {}):
            try:
                return self.fetch(url, **kw)
            except TypeError:
                continue
            except Exception:
                return None
        return None

    def _text(self, url, ref=None):
        r = self._fetch(url, ref)
        if r is None:
            return ""
        for attr in ("text", "content"):
            try:
                v = getattr(r, attr, None)
            except Exception:
                v = None
            if v is None:
                continue
            if isinstance(v, bytes):
                try:
                    return v.decode("utf-8", "replace")
                except Exception:
                    continue
            if isinstance(v, str) and v:
                return v
        try:
            j = r.json()
            return json.dumps(j, ensure_ascii=False)
        except Exception:
            return ""

    def _bytes(self, url, ref=None):
        r = self._fetch(url, ref)
        if r is None:
            return b""
        try:
            c = getattr(r, "content", None)
            if isinstance(c, bytes) and c:
                return c
        except Exception:
            pass
        try:
            t = getattr(r, "text", None)
            if isinstance(t, bytes):
                return t
            if isinstance(t, str):
                return t.encode("utf-8")
        except Exception:
            pass
        return b""

    def _page(self, url, ref=None):
        """带一层内存缓存（同一次会话内分类/筛选页会被反复取）"""
        if url in self._cache:
            return self._cache[url]
        t = self._text(url, ref)
        if len(self._cache) > 40:
            self._cache.clear()
        self._cache[url] = t
        return t

    # ---------------------------------------------------------------- 工具
    def _clean(self, s):
        if not s:
            return ""
        s = re.sub(r"(?s)<[^>]+>", "", s)
        s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
        for a, b in self._ENTS:
            s = s.replace(a, b)
        return re.sub(r"[ \t\r\n\u3000]+", " ", s).strip()

    def _q(self, v):
        return urllib.parse.quote((v or "").strip())

    @staticmethod
    def _b64(s):
        return base64.urlsafe_b64encode((s or "").encode("utf-8")).decode("utf-8").rstrip("=")

    @staticmethod
    def _ub64(s):
        s = (s or "").replace(" ", "+")
        s += "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s.encode("utf-8")).decode("utf-8", "replace")

    # ---------------------------------------------------------------- 首页
    def homeContent(self, filter):
        classes = [
            {"type_name": "电影", "type_id": "movie"},
            {"type_name": "电视剧", "type_id": "tv"},
        ]
        filters = {}
        if filter:
            for tid in ("movie", "tv"):
                try:
                    filters[tid] = self._filters(tid)
                except Exception:
                    filters[tid] = []
        return {"class": classes, "filters": filters}

    def homeVideoContent(self):
        try:
            txt = self._page("%s%s/" % (self.HOST, self.LANG))
            return {"list": self._list(txt)}
        except Exception:
            return {"list": []}

    def _filters(self, tid):
        ck = "f:" + tid
        if ck in self._cache:
            return self._cache[ck]
        txt = self._page("%s%s/%s/----onclick.html" % (self.HOST, self.LANG, tid))
        out = []

        # 排序（在 <header><dl> 里）
        sorts = []
        m = re.search(r"(?s)<header>\s*<dl>(.*?)</dl>", txt)
        if m:
            for a in re.finditer(r'href="[^"]*?/([A-Za-z]+)\.html"[^>]*>([^<]+)</a>', m.group(1)):
                sorts.append({"n": a.group(2).strip(), "v": a.group(1).strip()})
        if not sorts:
            sorts = [{"n": "按人气排序", "v": "onclick"},
                     {"n": "按时间排序", "v": "newstime"},
                     {"n": "按评分排序", "v": "rating"}]
        out.append({"key": "sort", "name": "排序", "value": sorts})

        # 类型 / 地区 / 年份（各自一个 <dl>，值按 href 的破折号位取）
        spec = [("genre", "类型", 0), ("area", "国家", 1), ("year", "年代", 2)]
        for key, label, idx in spec:
            vals = []
            for dm in re.finditer(r"(?s)<dl>(.*?)</dl>", txt):
                blk = dm.group(1)
                if label not in blk[:48]:
                    continue
                for a in re.finditer(r'href="[^"]*?/([^"/]*?)\.html"[^>]*>([^<]*)</a>', blk):
                    path, nm = a.group(1), self._clean(a.group(2))
                    parts = path.split("-")
                    if len(parts) < 3 or idx >= len(parts) or not nm:
                        continue
                    vals.append({"n": nm, "v": parts[idx]})
                break
            if vals:
                shown = {"genre": "类型", "area": "地区", "year": "年份"}[key]
                out.append({"key": key, "name": shown, "value": vals})

        self._cache[ck] = out
        return out

    # ---------------------------------------------------------------- 列表
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        extend = extend or {}
        g = extend.get("genre") or extend.get("class") or ""
        a = extend.get("area") or ""
        y = extend.get("year") or ""
        s = extend.get("sort") or "onclick"
        pnum = "" if pg <= 1 else str(pg - 1)
        url = "%s%s/%s/%s-%s-%s-%s-%s.html" % (
            self.HOST, self.LANG, tid, self._q(g), self._q(a), self._q(y), pnum, s)
        txt = self._page(url)
        lst = self._list(txt)
        return {
            "list": lst,
            "page": pg,
            "pagecount": self._pagecount(txt, pg, len(lst)),
            "limit": self.PER_PAGE,
            "total": 999999,
        }

    def _list(self, txt):
        out = []
        seen = set()
        if not txt:
            return out
        for blk in re.findall(r"(?s)<li>(.*?)</li>", txt):
            if 'class="thumbnail"' not in blk:
                continue
            mv = re.search(r'href="/(?:\w+/)?(movie|tv)/(\d+)\.html"', blk)
            if not mv:
                continue
            typ, vid = mv.group(1), mv.group(2)
            key = typ + "/" + vid
            if key in seen:
                continue

            name = ""
            tag = re.search(r"(?s)<img[^>]*class=\"thumb\"[^>]*>", blk)
            if tag:
                m1 = re.search(r'alt="([^"]*)"', tag.group(0))
                if m1:
                    name = self._clean(m1.group(1))
            if not name:
                m1 = re.search(r'title="([^"]*)"', blk)
                if m1:
                    name = self._clean(m1.group(1))
            if not name:
                m1 = re.search(r'h2>\s*<a[^>]*>([^<]*)</a>', blk)
                if m1:
                    name = self._clean(m1.group(1))
            if not name:
                continue

            seen.add(key)
            pic = ""
            m1 = re.search(r'(?s)<img[^>]*class="thumb"[^>]*>', blk)
            if m1:
                m2 = re.search(r'src="([^"]*)"', m1.group(0))
                if m2:
                    pic = m2.group(1)
            my = re.search(r'<span class="orange">(\d{4})</span>', blk)
            mn = re.search(r'<div class="note"><span>([^<]*)</span>', blk)
            mr = re.search(r'<span class="rate">([^<]*)</span>', blk)

            remark = []
            if mn and mn.group(1).strip():
                remark.append(mn.group(1).strip())
            if mr and mr.group(1).strip():
                remark.append(mr.group(1).strip() + "分")
            if my and my.group(1):
                remark.append(my.group(1))
            out.append({
                "vod_id": key,
                "vod_name": name,
                "vod_pic": pic,
                "vod_year": my.group(1) if my else "",
                "vod_remarks": " · ".join(remark),
            })
        return out

    def _pagecount(self, txt, pg, n):
        m = re.search(r'(?s)<div class="pagination[^"]*">(.*?)</div>', txt or "")
        if m:
            nums = [int(x) for x in re.findall(r">(\d+)</a>", m.group(1))]
            if nums:
                return max(max(nums), pg)
        return pg + 1 if n >= self.PER_PAGE else pg

    # ---------------------------------------------------------------- 搜索
    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        word = (key or "").strip().replace("-", " ")
        if not word:
            return {"list": [], "page": pg, "pagecount": pg, "limit": self.PER_PAGE, "total": 0}
        pnum = "" if pg <= 1 else str(pg - 1)
        url = "%s%s/search/%s-%s-.html" % (self.HOST, self.LANG, self._q(word), pnum)
        txt = self._text(url)
        lst = self._list(txt)
        return {
            "list": lst,
            "page": pg,
            "pagecount": self._pagecount(txt, pg, len(lst)),
            "limit": self.PER_PAGE,
            "total": 999999,
        }

    # ---------------------------------------------------------------- 详情
    def detailContent(self, ids):
        raw_id = ids[0] if isinstance(ids, (list, tuple)) and ids else str(ids)
        typ, vid = ("movie", str(raw_id).strip())
        if "/" in vid:
            typ, vid = vid.split("/", 1)
        txt = self._text("%s%s/%s/%s.html" % (self.HOST, self.LANG, typ, vid))
        vod = {"vod_id": "%s/%s" % (typ, vid), "vod_play_from": "PPnix"}
        if not txt:
            vod["vod_play_url"] = ""
            return {"list": [vod]}

        # 名称 / 海报（详情页首张 class=thumb 即主海报）
        mt = re.search(r'(?s)<img[^>]*class="thumb"[^>]*>', txt)
        if mt:
            t = mt.group(0)
            m1 = re.search(r'alt="([^"]*)"', t)
            m2 = re.search(r'src="([^"]*)"', t)
            if m1:
                vod["vod_name"] = self._clean(m1.group(1))
            if m2:
                vod["vod_pic"] = m2.group(1)
        if not vod.get("vod_name"):
            m1 = re.search(r'(?s)<h1 class="product-title">(.*?)</h1>', txt)
            if m1:
                vod["vod_name"] = self._clean(m1.group(1)).split("(")[0].strip()

        # 年份 / 评分
        m1 = re.search(r'(?s)<h1 class="product-title">(.*?)</h1>', txt)
        if m1:
            y = re.search(r"\((\d{4})\)", m1.group(1))
            if y:
                vod["vod_year"] = y.group(1)
            r = re.search(r'class="rate">([^<]*)<', m1.group(1))
            if r and r.group(1).strip():
                vod["vod_douban_score"] = r.group(1).strip()

        # 导演 / 主演 / 类型 / 国家 / 简介
        def ex(label):
            """取值时先把 </a> 换成占位符再剥标签 —— 直接在标签上按 / 切会把 href 切碎"""
            m = re.search(r'(?s)product-excerpt">\s*' + label + r'[:：]\s*<span>(.*?)</span>', txt)
            if not m:
                return ""
            inner = re.sub(r"(?i)</a>", "\u0001", m.group(1))
            inner = re.sub(r"(?s)<[^>]+>", "", inner)
            inner = re.sub(r"&#(\d+);", lambda x: chr(int(x.group(1))), inner)
            for a, b in self._ENTS:
                inner = inner.replace(a, b)
            parts = []
            for p in inner.split("\u0001"):
                p = p.strip().strip("/").strip()
                if p:
                    parts.append(p)
            return "，".join(parts)
        vod["vod_director"] = ex("导演")
        vod["vod_actor"] = ex("主演")
        tp = ex("类型")
        if tp:
            vod["type_name"] = tp.replace("，", "/")
            vod["vod_type"] = vod["type_name"]
        vod["vod_area"] = ex("国家")
        m1 = re.search(r'(?s)product-excerpt">\s*简介[:：]\s*<span>(.*?)</span>', txt)
        if m1:
            vod["vod_content"] = self._clean(m1.group(1))

        # 剧集（内联变量 m3u8=['1080P'] 或 ['1','2',...]）
        labels = []
        m1 = re.search(r"m3u8\s*=\s*(\[[^\]]*\])", txt)
        if m1:
            try:
                labels = json.loads(m1.group(1).replace("'", '"'))
            except Exception:
                labels = re.findall(r"'([^']*)'", m1.group(1))
        if not labels:
            labels = ["1080P"] if typ == "movie" else ["1"]
        eps = []
        for lb in labels:
            lb = str(lb).strip()
            if not lb:
                continue
            nm = ("第%d集" % int(lb)) if re.match(r"^\d+$", lb) else lb
            eps.append("%s$%s/info/m3u8/%s/%s.m3u8" % (nm, self.HOST, vid, lb))
        vod["vod_play_url"] = "#".join(eps)
        if typ == "tv" and eps:
            vod["vod_remarks"] = "共%d集" % len(eps)
        return {"list": [vod]}

    # ---------------------------------------------------------------- 播放
    def playerContent(self, flag, id, vipFlags):
        url = id or ""
        if not url.startswith("http"):
            # 容错：若传入的是 movie/8458|1080P 这类标识
            vid, lb = url, ""
            if "|" in url:
                vid, lb = url.split("|", 1)
            if "/" in vid:
                vid = vid.split("/", 1)[1]
            url = "%s/info/m3u8/%s/%s.m3u8" % (self.HOST, vid, lb or "1080P")
        if self.USE_PROXY and self.isVideoFormat(url):
            try:
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": self.getProxyUrl() + "&type=m3u8&url=" + self._b64(url),
                    "header": self._hdr(),
                }
            except Exception:
                pass
        return {"parse": 0, "playUrl": "", "url": url, "header": self._hdr()}

    # ---------------------------------------------------------------- 代理
    # 仅在 USE_PROXY=True 时被调用：把 32 字节 key 裁成 16 字节，供 ExoPlayer 内核使用
    def localProxy(self, param):
        try:
            typ = (param or {}).get("type") or ""
            url = self._ub64((param or {}).get("url") or "")
            if not url:
                return [404, "text/plain", ""]
            data = self._bytes(url, ref=self.HOST + "/")
            if typ == "key":
                return [200, "application/octet-stream", data[:16]]
            txt = data.decode("utf-8", "replace")
            # 关键：m3u8 里的 key URI 是相对的 "../key" → 必须按播放列表地址做相对解析，
            # 解出来是 /info/m3u8/key（不是 /info/m3u8/{id}/key）。该文件 32 字节，
            # 这里由代理裁成 16 字节再喂给播放器，保证 ExoPlayer 内核也能正常解密。
            km = re.search(r'URI="([^"]*)"', txt)
            if km:
                kurl = urllib.parse.urljoin(url, km.group(1))
                try:
                    kprox = self.getProxyUrl() + "&type=key&url=" + self._b64(kurl)
                except Exception:
                    kprox = kurl
                txt = re.sub(r'URI="[^"]*"', 'URI="%s"' % kprox, txt, count=1)
            lines = []
            for line in txt.split("\n"):
                s = line.strip()
                if s and not s.startswith("#") and "://" not in s:
                    s = urllib.parse.urljoin(url, s)
                lines.append(s)
            return [200, "application/vnd.apple.mpegurl", "\n".join(lines)]
        except Exception:
            return [200, "text/plain", ""]
