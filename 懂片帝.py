# coding=utf-8
"""
懂片帝（dongpian.ai）—— TVBox Python 蜘蛛（py 源）

站点：https://dongpian.ai  （推广参数 ?utm_source=WZ-kele 仅用于来源统计，可忽略）
站型：React SPA + 同源 REST API（/v1/...），**全部接口要求逐请求 HMAC 签名**。

★ 关键信息（均已实测打通）：
  1. 所有 /v1/ 接口必须在请求头带三件套：
        x-ai-movie-timestamp : 毫秒时间戳（Date.now()）
        x-ai-movie-nonce     : 随机串
        x-ai-movie-signature : HMAC-SHA256(SECRET, "METHOD\\nPATH?QUERY\\n时间戳\\n随机数")
     签名密钥 SECRET 硬编码在前端 JS（global-player-host / movie-card-runtime 里
     `Vo="8b9a...666"`），本文件原样内置。
  2. **无需登录 / 无需会话 cookie**：匿名接口 /v1/users/anonymous 下发的是
     Max-Age=0 的过期 cookie，等于没用；而 browse / catalog / episodes / suggest
     仅凭签名即可 200。所以本源「每次请求自动签名」即可，用户零配置。
  3. 播放链路：详情/剧集接口只给每集一个 `token`，真实 m3u8 由站内播放器
     解析。播放页就是站方自己的 SPA 页面：
        https://dongpian.ai/__react-player-target?url=<token>
     → 交 TVBox webview **嗅探（parse=1）** 出真实 HLS 直链，与网页播放路径完全一致。

★ 接口清单（逆向自前端 JS，均实测 200）：
   首页推荐  GET /v1/feed/home?limit=20            → sections[].cards[]
   分类列表  GET /v1/browse/catalog?kind=KIND&page=P&limit=20&intent=latest_catalog
   详情      GET /v1/catalog/{id}
   剧集      GET /v1/catalog/{id}/episodes?offset=0&limit=48  → episodes[].token
   搜索      GET /v1/suggest?q=KEYWORD            → suggestions[].target.variant_id
             （站无独立 catalog 搜索端点，故搜索用 suggest 命中后逐条补详情拿封面）

★ 分类 kind（来自 JS 枚举 L）：movie/series/short_drama/anime/variety/documentary/sports/adult
   中文名（Cf 映射）：电影/剧集/短剧/动漫/综艺/纪录片/体育/18+（adult 默认不列，可按需开启）。
"""

import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


# TVBox 运行环境提供 base.spider；本地自测时退回 stub，让 _fetch 走 urllib。
try:
    from base.spider import Spider as _BaseSpider
    _HAS_BASE = True
except Exception:
    class _BaseSpider:
        pass
    _HAS_BASE = False


class Spider(_BaseSpider):

    BASE = "https://dongpian.ai"
    SECRET = "8b9a908a05eac640e1ee06f52acaa741bfe4ba9e004eeffdbeb635e532e06666"
    PLAYER_TARGET = "/__react-player-target"          # 站内播放器页面（SPA 解析 m3u8）
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

    # kind -> 中文名（与前端 Cf 映射一致；adult 不列）
    KINDS = [
        ("movie", "电影"),
        ("series", "剧集"),
        ("short_drama", "短剧"),
        ("anime", "动漫"),
        ("variety", "综艺"),
        ("documentary", "纪录片"),
        ("sports", "体育"),
    ]

    PAGE = 20                                        # 每页条数

    # ================= 基础 =================

    def getName(self):
        return "懂片帝"

    def init(self, extend=""):
        self.base = self.BASE
        self._cache = {}                             # 简单缓存，避免详情重复拉取

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(m3u8|mp4|flv)(\?|$)", url or ""))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ================= 签名 + HTTP =================

    @staticmethod
    def _nonce():
        return uuid.uuid4().hex[:16]

    @classmethod
    def _sign(cls, method, path_query, ts, nonce):
        msg = "%s\n%s\n%s\n%s" % (method, path_query, ts, nonce)
        return hmac.new(cls.SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _rtxt(r):
        try:
            if getattr(r, "text", None):
                return r.text
        except Exception:
            pass
        try:
            return (r.content or b"").decode("utf-8", "ignore")
        except Exception:
            return ""

    def _fetch(self, method, path, params=None):
        """带签名的请求，返回响应文本。TVBox 走 self.fetch，本地走 urllib。"""
        url = self.base + path
        pq = path
        if params:
            q = urllib.parse.urlencode(params)
            url += "?" + q
            pq = path + "?" + q
        ts = str(int(time.time() * 1000))            # 毫秒！
        nc = self._nonce()
        sig = self._sign(method, pq, ts, nc)
        headers = {
            "User-Agent": self.UA,
            "Accept": "application/json, text/plain, */*",
            "x-ai-movie-timestamp": ts,
            "x-ai-movie-nonce": nc,
            "x-ai-movie-signature": sig,
            "Origin": self.base,
            "Referer": self.base + "/",
        }
        # TVBox 环境：self.fetch 由宿主提供
        if _HAS_BASE:
            try:
                resp = self.fetch(url, headers=headers, method=method)
                txt = self._rtxt(resp)
                if txt:
                    return txt
            except Exception:
                pass
        # 本地 / 兜底：urllib
        req = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            return e.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    def _json(self, method, path, params=None):
        try:
            return json.loads(self._fetch(method, path, params) or "{}")
        except Exception:
            return {}

    # ================= 卡片解析（列表 / 首页 / 搜索 共用） =================

    @staticmethod
    def _clean(s):
        return re.sub(r"\s+", " ", (s or "")).strip()

    @classmethod
    def _card(cls, c):
        if not isinstance(c, dict):
            return None
        cid = c.get("id") or c.get("variant_id") or ""
        if not cid:
            return None
        title = c.get("title") or c.get("label") or ""
        if not title:
            return None
        return {
            "vod_id": cid,
            "vod_name": cls._clean(title),
            "vod_pic": c.get("poster_url") or c.get("carousel_url") or "",
            "vod_remarks": cls._clean(c.get("remarks") or c.get("subtitle") or ""),
        }

    @classmethod
    def _cards_from(cls, data):
        out, seen = [], set()
        cards = data.get("cards")
        if not isinstance(cards, list):
            # feed/home：sections[].cards[]
            for sec in data.get("sections", []) or []:
                if isinstance(sec, dict):
                    cards = sec.get("cards") or []
                    for c in cards:
                        cd = cls._card(c)
                        if cd and cd["vod_id"] not in seen:
                            seen.add(cd["vod_id"])
                            out.append(cd)
            return out
        for c in cards:
            cd = cls._card(c)
            if cd and cd["vod_id"] not in seen:
                seen.add(cd["vod_id"])
                out.append(cd)
        return out

    # ================= 首页 / 分类 / 搜索 =================

    def homeContent(self, filter):
        return {"class": [{"type_id": k, "type_name": n} for k, n in self.KINDS]}

    def homeVideoContent(self):
        data = self._json("GET", "/v1/feed/home", {"limit": 20})
        lst = self._cards_from(data)
        if not lst:                                   # 兜底：最新电影
            data = self._json("GET", "/v1/browse/catalog",
                              {"kind": "movie", "page": 1, "limit": self.PAGE,
                               "intent": "latest_catalog"})
            lst = self._cards_from(data)
        return {"list": lst}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg) if pg else 1
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        data = self._json("GET", "/v1/browse/catalog",
                          {"kind": tid, "page": pg, "limit": self.PAGE,
                           "intent": "latest_catalog"})
        lst = self._cards_from(data)
        total = (data.get("pagination") or {}).get("total", 0) or (len(lst) * 999)
        pagecount = max(1, (int(total) + self.PAGE - 1) // self.PAGE)
        return {"list": lst, "page": pg, "pagecount": pagecount,
                "limit": self.PAGE, "total": int(total)}

    def searchContent(self, key, quick, pg=1):
        key = self._clean(key)
        if not key:
            return {"list": []}
        try:
            pg = int(pg) if pg else 1
        except Exception:
            pg = 1
        if pg > 1:                                    # suggest 无翻页
            return {"list": [], "page": pg}
        sug = self._json("GET", "/v1/suggest", {"q": key})
        sugs = sug.get("suggestions") or []
        out = []
        for s in sugs[:12]:                            # 取前 12 条补详情拿封面
            vid = (s.get("target") or {}).get("variant_id") or s.get("id")
            if not vid:
                continue
            d = self._json("GET", "/v1/catalog/" + vid)
            c = self._card({
                "id": vid,
                "title": d.get("title") or s.get("label"),
                "poster_url": d.get("poster_url"),
                "remarks": d.get("remarks") or s.get("subtitle"),
            })
            if c:
                out.append(c)
            if len(out) >= 12:
                break
        return {"list": out, "page": pg}

    # ================= 详情 =================

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = str(vid).strip().strip("/").split("/")[-1]
        d = self._json("GET", "/v1/catalog/" + vid)
        if not d or not d.get("id"):
            return {"list": []}
        # 剧集（详情里可能内联 episodes，否则单独拉）
        eps = d.get("episodes") or []
        if not isinstance(eps, list) or not eps:
            epd = self._json("GET", "/v1/catalog/" + vid + "/episodes",
                             {"offset": 0, "limit": 48})
            eps = epd.get("episodes") or []
        urls = []
        for e in eps:
            if not isinstance(e, dict):
                continue
            token = e.get("token") or ""
            if not token:
                continue
            name = self._clean(e.get("title") or ("第%d集" % (len(urls) + 1)))
            # 播放 id 直接用 token；playerContent 据此拼站内播放页
            urls.append("%s$%s" % (name, token))
        if not urls:
            return {"list": []}
        vod = {
            "vod_id": vid,
            "vod_name": self._clean(d.get("title") or ""),
            "vod_pic": d.get("poster_url") or "",
            "vod_content": self._clean(d.get("description") or ""),
            "vod_actor": " / ".join(d.get("actors") or []) if isinstance(d.get("actors"), list) else "",
            "vod_director": " / ".join(d.get("directors") or []) if isinstance(d.get("directors"), list) else "",
            "vod_area": d.get("area") or "",
            "vod_year": str(d.get("year") or ""),
            "type_name": " / ".join(d.get("genres") or []) if isinstance(d.get("genres"), list) else "",
            "vod_remarks": self._clean(d.get("remarks") or ""),
            "vod_play_from": "直播",
            "vod_play_url": "#".join(urls),
        }
        return {"list": [vod]}

    # ================= 播放 =================

    def playerContent(self, flag, id, vipFlags):
        token = (id or "").strip()
        if not token or not token.startswith("av_"):
            return {"parse": 1, "url": self.base + "/"}
        url = self.base + self.PLAYER_TARGET + "?url=" + urllib.parse.quote(token, safe="")
        return {
            "parse": 1,                                # 站内播放器页面，交 TVBox 嗅探真实 m3u8
            "url": url,
            "header": {"User-Agent": self.UA, "Referer": self.base + "/"},
        }

    # ================= 本地代理（源站直链，无需代理） =================

    def localProxy(self, param):
        return None


# ================= 本地自测（python dongpian.py） =================
if __name__ == "__main__":
    sp = Spider()
    sp.init("")
    print("== 分类 ==")
    print(sp.homeContent(False)["class"])

    print("\n== 首页推荐 ==")
    hv = sp.homeVideoContent()["list"]
    print("条数:", len(hv))
    if hv:
        print("示例:", hv[0]["vod_name"], hv[0]["vod_id"])

    print("\n== 分类列表（剧集 第1页）==")
    cat = sp.categoryContent("series", 1, {}, "")
    print("条数:", len(cat["list"]), "pagecount:", cat["pagecount"])
    if cat["list"]:
        print("示例:", cat["list"][0]["vod_name"], cat["list"][0]["vod_id"])

    print("\n== 详情 + 剧集 ==")
    vid = cat["list"][0]["vod_id"]
    det = sp.detailContent([vid])["list"][0]
    print("名称:", det["vod_name"], "| 集数:", det["vod_play_url"].count("#") + 1)
    print("首集 play_id:", det["vod_play_url"].split("#")[0].split("$")[1][:30], "...")

    print("\n== 播放链接 ==")
    tok = det["vod_play_url"].split("#")[0].split("$")[1]
    pc = sp.playerContent("直播", tok, "")
    print(pc["url"])

    print("\n== 搜索（独剑）==")
    sr = sp.searchContent("独剑", True, 1)["list"]
    print("条数:", len(sr))
    for x in sr[:5]:
        print(" -", x["vod_name"], "|", x["vod_id"])
