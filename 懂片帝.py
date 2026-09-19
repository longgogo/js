# coding=utf-8
"""
懂片帝 / dongpian.ai —— TVBox Python 蜘蛛（py 源）

站点：https://dongpian.ai  （AI 生成影视站，React SPA）
站型：全部数据走同源 REST API（dongpian.ai/v1/...），前端为 React + Vite 懒加载 chunk。

★ 全站 /v1/ 接口要求「逐请求 HMAC 签名」+ 一组客户端头，否则 401：
   签名头：x-ai-movie-timestamp(毫秒) / x-ai-movie-nonce(16字节随机hex) / x-ai-movie-signature
   签名串： METHOD\n<pathname+search>\n<毫秒时间戳>\n<nonce>
   算法：   HMAC-SHA256(SECRET, 签名串) → 小写 hex
   客户端头：x-ai-movie-client-name / -client-version / -build-version / -protocol-version
   注意：SECRET 由站方维护，若日后接口返回 401(invalid_request_signature)，
         用浏览器 DevTools 在 movie-card-runtime 这个 chunk 里搜 `Vo="..."` 取新值替换下方 SECRET 一行即可。

★ 播放（已实测，parse=0 直出，不依赖嗅探）：
   详情接口 /v1/catalog/{id} 的 episodes[].token 是每集令牌；
   播放解析接口 GET /v1/playback/resolve/{token} 直接返回各线路真实直链
   （line_options[].url，url_kind 多为 m3u8，resolved:true）。
   本源取「默认选中线路」或第一条已解析线路的 url，parse=0 直出给 TVBox。

★ 列表/详情/搜索均凭签名即可访问，无需登录、无需 token。
"""

import hmac
import hashlib
import json
import os
import re
import time
import urllib.request
import urllib.error
import urllib.parse

try:
    from base.spider import Spider
    _HAS_BASE = True
except Exception:
    _HAS_BASE = False


class Spider(object if not _HAS_BASE else Spider):

    BASE = "https://dongpian.ai"
    # 站方 HMAC 密钥（movie-card-runtime chunk 里的 Vo 常量，需随站方轮换更新）
    SECRET = "8b9a908a05eac640e1ee06f52acaa741bfe4ba9e004eeffdbeb635e532e06666"
    CLIENT_HEADERS = {
        "x-ai-movie-client-name": "movie-search-frontend",
        "x-ai-movie-client-version": "1.0.0",
        "x-ai-movie-build-version": "dongpiandi-v2026.09.18.3-1b60ec6ec254-web",
        "x-ai-movie-protocol-version": "2026-07-05.library-v2.playback-v1",
    }
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

    # 分类（kind 枚举，对应 /v1/browse/catalog?kind=）
    CATEGORIES = [
        ("movie", "电影"),
        ("series", "剧集"),
        ("short_drama", "短剧"),
        ("anime", "动漫"),
        ("variety", "综艺"),
        ("documentary", "纪录片"),
        ("sports", "体育"),
    ]

    def getName(self):
        return "懂片帝"

    def init(self, extend=""):
        self.extend = (extend or "").strip()

    # ================= 签名 + HTTP =================

    @staticmethod
    def _sign(method, path_query):
        ts = str(int(time.time() * 1000))
        nonce = "".join("%02x" % b for b in os.urandom(16))   # 16 字节随机 → 32 hex
        msg = "%s\n%s\n%s\n%s" % (method, path_query, ts, nonce)
        sig = hmac.new(Spider.SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "x-ai-movie-timestamp": ts,
            "x-ai-movie-nonce": nonce,
            "x-ai-movie-signature": sig,
        }

    def _apiget(self, path, params=None):
        return self._apireq("GET", path, params)

    def _apireq(self, method, path, params=None, body=None, _attempt=0):
        pq = ("?" + urllib.parse.urlencode(params)) if params else ""
        url = self.BASE + path + pq
        h = dict(self.CLIENT_HEADERS)
        h.update(self._sign(method, path + pq))
        h["User-Agent"] = self.UA
        h["Accept"] = "application/json"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            # 400/429/5xx 多为限流或瞬时抖动，重试；401 是签名问题不重试（已修正 SECRET）
            txt = e.read().decode("utf-8", "ignore")
            if e.code in (400, 429, 500, 502, 503, 504) and _attempt < 2:
                time.sleep(1.0)
                return self._apireq(method, path, params, body, _attempt + 1)
            return txt
        except Exception as e:
            if _attempt < 2:
                time.sleep(1.0)
                return self._apireq(method, path, params, body, _attempt + 1)
            return "ERR:%s" % e

    @staticmethod
    def _j(text, default=None):
        try:
            return json.loads(text)
        except Exception:
            return default

    # ================= 列表 =================

    def homeContent(self, filter):
        return {"class": [{"type_id": tid, "type_name": tname}
                          for tid, tname in self.CATEGORIES]}

    def homeVideoContent(self):
        # 首页推荐：用 feed/home 的 sections[].cards，结构同列表卡片
        txt = self._apiget("/v1/feed/home")
        d = self._j(txt)
        cards = []
        if isinstance(d, dict):
            data = d.get("data", d)
            secs = data.get("sections") if isinstance(data, dict) else None
            if isinstance(secs, list):
                for sec in secs:
                    cards += (sec or {}).get("cards", []) or []
        if not cards:
            cards = self._browse("movie", 1, 20) or []
        return {"list": [self._card(c) for c in cards if c]}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        cards = self._browse(tid, pg, 20) or []
        return {"list": [self._card(c) for c in cards if c], "page": pg,
                "pagecount": 9999, "limit": 20, "total": 999999}

    def _browse(self, kind, page, limit):
        txt = self._apiget("/v1/browse/catalog", {
            "kind": kind, "page": page, "limit": limit,
            "intent": "latest_catalog",
        })
        d = self._j(txt)
        if not isinstance(d, dict):
            return []
        data = d.get("data", d)
        if not isinstance(data, dict):
            return []
        return data.get("cards") or []

    @staticmethod
    def _card(c):
        if not isinstance(c, dict):
            return None
        title = c.get("title") or c.get("normalized_title") or ""
        if not title:
            return None
        return {
            "vod_id": c.get("id") or c.get("work_id") or "",
            "vod_name": title,
            "vod_pic": c.get("poster_url") or "",
            "vod_remarks": c.get("remarks") or "",
            "vod_year": c.get("year") or "",
        }

    def searchContent(self, key, quick, pg=1):
        key = (key or "").strip()
        if not key:
            return {"list": []}
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        # /v1/suggest?q= 返回 { suggestions:[ {target:{variant_id,title}, label, subtitle} ] }
        # 直接以 target.variant_id 作为 vod_id 出卡片（仅 1 次请求，稳定且快）；
        # TVBox 点击时 detailContent 再按 variant_id 拉取完整详情与播放线路。
        txt = self._apiget("/v1/suggest", {"q": key})
        d = self._j(txt)
        if not isinstance(d, dict):
            return {"list": []}
        sug = d.get("suggestions") or []
        lst = []
        for s in sug:
            if not isinstance(s, dict):
                continue
            tgt = s.get("target") or {}
            vid = (tgt.get("variant_id") or tgt.get("id")
                   or s.get("variant_id") or s.get("id"))
            if not vid:
                continue
            name = tgt.get("title") or s.get("label") or s.get("title") or ""
            if not name:
                continue
            lst.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_remarks": s.get("subtitle") or "",
            })
            if len(lst) >= 20:
                break
        return {"list": lst, "page": pg}

    # ================= 详情 =================

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = str(vid).strip().strip("/").split("/")[-1]
        d = self._detail(vid)
        return {"list": [d] if d else []}

    def _detail(self, vid):
        txt = self._apiget("/v1/catalog/%s" % urllib.parse.quote(vid, safe=""))
        d = self._j(txt)
        if not isinstance(d, dict):
            return None
        data = d.get("data", d)
        if not isinstance(data, dict):
            return None
        title = data.get("title") or data.get("normalized_title") or ""
        if not title:
            return None
        # 主接口偶尔不返回 episode token；专用 /episodes 接口稳定返回 token，优先使用
        episodes = self._episodes(vid)
        if not episodes:
            episodes = data.get("episodes") or []
        froms, urls = self._build_lines(episodes)
        return {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": data.get("poster_url") or "",
            "vod_content": data.get("description") or "",
            "vod_actor": " ".join(data.get("actors") or []),
            "vod_director": " ".join(data.get("directors") or []),
            "vod_area": data.get("area") or "",
            "vod_year": data.get("year") or "",
            "vod_remarks": data.get("remarks") or "",
            "vod_play_from": "$$$".join(froms) if froms else "懂片帝",
            "vod_play_url": "$$$".join(urls) if urls else "",
        }

    def _episodes(self, vid):
        """专用分集接口 /v1/catalog/{id}/episodes：稳定返回每集 token；支持分页。
        偶发返回空（限流/抖动/瞬时 200 空体）时首页重试，避免误判为无线路。"""
        acc = []
        offset = 0
        for _ in range(5):
            params = {"limit": 50}
            if offset:
                params["offset"] = offset
            txt = self._apiget("/v1/catalog/%s/episodes" % urllib.parse.quote(vid, safe=""), params)
            d = self._j(txt)
            if not isinstance(d, dict):
                break
            data = d.get("data", d)
            if not isinstance(data, dict):
                break
            eps = data.get("episodes") or []
            if not eps and offset == 0:
                time.sleep(1.2)
                continue                       # 首页偶发为空，重试
            acc += eps
            pg = data.get("episode_pagination") or {}
            if pg.get("has_more") and eps:
                total = pg.get("total_count") or 999999
                if len(acc) < total:
                    offset += len(eps)
                    continue
            break
        return acc

    def _build_lines(self, episodes):
        """每集一行为 集名$token；单线路（默认选中线路）。"""
        if not isinstance(episodes, list) or not episodes:
            return [], []
        eps = []
        for e in episodes:
            if not isinstance(e, dict):
                continue
            token = e.get("token")
            if not token:
                continue
            name = e.get("title") or ("第%d集" % (e.get("number") or (len(eps) + 1)))
            eps.append("%s$%s" % (name, token))
        if not eps:
            return [], []
        # 单线路：所有集用同一个 from，url 用 # 连接
        return ["懂片帝"], ["#".join(eps)]

    # ================= 播放（parse=0 直出 m3u8） =================

    def playerContent(self, flag, id, vipFlags):
        raw = (id or "").strip()
        if "$" in raw:
            raw = raw.split("$")[-1]   # 兼容不同分隔写法
        if not raw:
            return {"parse": 1, "url": self.BASE + "/"}
        # raw 即为 episode token
        txt = self._apiget("/v1/playback/resolve/%s" % urllib.parse.quote(raw, safe=""))
        d = self._j(txt)
        if not isinstance(d, dict):
            return {"parse": 1, "url": self.BASE + "/"}
        lines = d.get("line_options") or []
        url = ""
        # 优先选「真实 m3u8 直链」线路（url_kind=m3u8 且已解析、http 开头）；
        # 前几条 official-* / bytevod-* 是 resolve_ticket 占位符，需二次 resolve-line，跳过。
        for ln in lines:
            if not isinstance(ln, dict):
                continue
            u = ln.get("url") or ""
            if (ln.get("url_kind") == "m3u8" and not ln.get("resolve_required")
                    and u.startswith("http")):
                url = u
                break
        if not url:                       # 退而求其次：任意已解析的 http 直链
            for ln in lines:
                if isinstance(ln, dict) and str(ln.get("url") or "").startswith("http"):
                    url = ln["url"]
                    break
        if not url:
            return {"parse": 1, "url": self.BASE + "/"}
        return {
            "parse": 0,
            "url": url,
            "header": {
                "User-Agent": self.UA,
                "Referer": self.BASE + "/",
            },
        }

    # ================= 本地代理 =================
    def localProxy(self, param):
        return None

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(m3u8|mp4|flv)(\?|$)", url or "")) if url else False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass


# ================= 本地自测 =================
if __name__ == "__main__":
    sp = Spider()
    sp.init("")
    print("== 分类 ==", [t[1] for t in sp.CATEGORIES])
    cards = sp._browse("series", 1, 5) or []
    print("== 剧集列表(5) ==", [(c.get("title"), c.get("id")) for c in cards if c])
    if cards:
        vid = (cards[0] or {}).get("id")
        det = sp._detail(vid)
        print("== 详情 ==", det.get("vod_name"), "剧集数:", det.get("vod_play_url", "").count("#") + (1 if det.get("vod_play_url") else 0))
        toks = re.findall(r"\$([^\#]+)", det.get("vod_play_url", ""))
        if toks:
            pc = sp.playerContent("懂片帝", toks[0], "")
            print("== 播放 ==", pc.get("parse"), pc.get("url"))
    print("== 搜索'独剑' ==")
    r = sp.searchContent("独剑", False, 1)
    print("   命中:", [x.get("vod_name") for x in r.get("list", [])][:5])
