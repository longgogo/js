# coding=utf-8
"""
两个BT影视 —— TVBox Python 蜘蛛（py 源）

站点：https://www.bttwo.top     备用域名：https://www.bttwo.life
（`www.bttwo.me` / `www.bttwo.org` 国内已和谐，不要用）

站型：自研 Go + Alpine.js 服务端渲染，无任何 MacCMS 路由。
  分类   /filter?classify={1|2|3}&page={n}     （1=电影 2=电视剧 3=动漫，4 无内容）
  详情   /play/{hash}                          （详情页 = 播放页，剧集内嵌 dataid）
  搜索   /search?q={utf-8}                     （无验证码，但**不支持翻页**）
  播控   /video/play?p=&v=&q=&s=&t=&k=

播放地址由站点 WASM（nbmovie_wasm）现算签名：
  s = HMAC-SHA256(key = v_hash, msg = "{dataid}:{毫秒时间戳}:{v_hash}") 的前 16 字节 hex
  k = URL-safe-Base64( xor( 页面注入的游客令牌, 循环密钥 "nbmovie2024secretkey" ) )
本文件用 Python 的 hmac/hashlib/base64 完整复现了这两步，因此**不需要 TVBox 嗅探**，
playerContent 直接返回 1080p 明文 m3u8（parse=0）；4K 为 VIP 锁会自动跳过。
拿不到直链时兜底回播放页（parse=1）。
"""
import base64
import hashlib
import hmac
import json
import re
import time
import urllib.parse

from base.spider import Spider


class Spider(Spider):

    # ---- 站点常量 ----
    DEFAULT_HOST = "https://www.bttwo.top"
    SECRET = "nbmovie2024secretkey"
    UA = ("Mozilla/5.0 (Linux, Android 11) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/126.0.0.0 Mobile Safari/537.36")
    TOKEN_TTL = 60           # 游客令牌缓存秒数（实测偏短时效，失败会自动重抓重试）

    # 列表卡片：分类页每卡 3 个 <a>，只有这一个 class="block" 且含 data-src 的才是海报卡
    _CARD = re.compile(r'(?s)<a href="/play/([A-Za-z0-9]+)" class="block">((?:(?!</a>).)*?)</a>')
    # 剧集条目：属性里有 `=>`（Alpine 箭头函数）与 `getAttribute('href')`，
    # 不能用 [^>]* / [^)]* 匹配，必须用 (?!</a>) 守卫
    _EP = re.compile(
        r'(?s)<a href="(/play/[A-Za-z0-9]+)"[^>]*?handleEpisodeClick\('
        r'(?:(?!</a>).)*?\'(\d+)\',\s*(\d+),\s*(\d+)\)((?:(?!</a>).)*?)</a>')

    # ================= 基础 =================

    def getName(self):
        return "两个BT影视"

    def init(self, extend=""):
        host = (extend or "").strip()
        if not host:
            host = self.DEFAULT_HOST
        if not host.startswith("http"):
            host = "https://" + host
        self.host = host.rstrip("/")
        self._tok = ""
        self._tok_ts = 0.0

    def isVideoFormat(self, url):
        return True if re.search(r"\.(m3u8|mp4)(\?|$)", url or "") else False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ---- HTTP ----

    def _req(self, url, referer=None, timeout=20):
        h = {
            "User-Agent": self.UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if referer:
            h["Referer"] = referer
        for kw in ({"headers": h, "timeout": timeout, "allow_redirects": True},
                   {"headers": h, "timeout": timeout},
                   {"headers": h}):
            try:
                return self.fetch(url, **kw)
            except TypeError:
                continue          # 宿主不收这个参数（发生在发请求前）
            except Exception:
                return None
        return None

    def _text(self, url, referer=None, timeout=20):
        r = self._req(url, referer, timeout)
        if r is None:
            return ""
        try:
            t = r.text
            if t:
                return t
        except Exception:
            pass
        try:
            return (r.content or b"").decode("utf-8", "ignore")
        except Exception:
            return ""

    @staticmethod
    def _unesc(s):
        if not s:
            return ""
        return (s.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
                 .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " "))

    @staticmethod
    def _clean(s):
        return re.sub(r"\s+", " ", (s or "")).strip()

    # ================= 列表 =================

    def _cards(self, html):
        """首页 / 分类页 / 搜索页 三处共用（三处卡片 DOM 不同，锚点相同）。"""
        out, seen = [], set()
        for vid, blk in self._CARD.findall(html or ""):
            if vid in seen or "data-src=" not in blk or "aspect-video" in blk:
                continue
            mname = re.search(r'alt="([^"]*)"', blk)
            name = self._unesc(mname.group(1)) if mname else ""
            if not name or name in ("item.title",):
                continue          # Alpine 模板骨架，不是真实数据
            mpic = re.search(r'data-src="([^"]+)"', blk)
            mrem = re.search(r'text-right[^>]*>([^<]*)<', blk)
            seen.add(vid)
            out.append({
                "vod_id": vid,
                "vod_name": self._clean(name),
                "vod_pic": self._unesc(mpic.group(1) if mpic else ""),
                "vod_remarks": self._clean(mrem.group(1)) if mrem else "",
            })
        return out

    def homeContent(self, filter):
        return {
            "class": [
                {"type_id": "1", "type_name": "电影"},
                {"type_id": "2", "type_name": "电视剧"},
                {"type_id": "3", "type_name": "动漫"},
            ]
        }

    def homeVideoContent(self):
        return {"list": self._cards(self._text(self.host + "/"))}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        url = "%s/filter?classify=%s&page=%d" % (self.host, tid, pg)
        lst = self._cards(self._text(url, referer=self.host + "/"))
        return {"list": lst, "page": pg, "pagecount": 9999,
                "limit": len(lst) or 24, "total": 999999}

    def searchContent(self, key, quick, pg=1):
        key = self._clean(key)
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if not key or pg > 1:
            return {"list": [], "page": pg}      # 站点搜索不支持翻页
        url = self.host + "/search?q=" + urllib.parse.quote(key, safe="")
        return {"list": self._cards(self._text(url, referer=self.host + "/")), "page": pg}

    # ================= 详情 =================

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = str(vid).strip().strip("/").split("/")[-1]
        d = self._detail(vid)
        return {"list": [d]} if d else {"list": []}

    def _detail(self, vid):
        page_url = "%s/play/%s" % (self.host, vid)
        html = self._text(page_url, referer=self.host + "/")
        if not html:
            return None

        def meta(prop):
            m = re.search(r'<meta[^>]*property="%s"[^>]*content="([^"]*)"' % re.escape(prop), html)
            return self._unesc(m.group(1)) if m else ""

        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        name = self._clean(self._unesc(m.group(1))) if m else ""
        if not name:
            name = self._clean(meta("og:title").split("-")[0])

        def field(label):
            m = re.search(r'>\s*' + re.escape(label) +
                          r'\s*</div>\s*<div class="col-span-2[^"]*">(.*?)</div>', html, re.S)
            return self._clean(self._unesc(m.group(1))) if m else ""

        # 线路名（服务端写死在 Alpine 初始化里）
        line_names = []
        m = re.search(r'episodeManager\(\s*\d+\s*,\s*\d+\s*,\s*\[(.*?)\]\s*\)', html, re.S)
        if m:
            line_names = re.findall(r"lineName:\s*'([^']*)'", m.group(1))
        alias = {"alists": "云播", "hitv": "云播", "": ""}

        groups = {}
        for mh, md, mline, mep, body in self._EP.findall(html):
            ln = int(mline) or 1
            mt = re.search(r'x-show="!isEpisodeActive\(\d+,\s*\d+\)"\s*>\s*([^<]*?)\s*<', body)
            ep = self._clean(mt.group(1)) if mt else ""
            if not ep:
                ep = self._clean(mep) or ("第%d集" % (len(groups.get(ln, [])) + 1))
            ep = "%s$%s|%s" % (ep, mh.strip("/").split("/")[-1], md)
            groups.setdefault(ln, []).append(ep)

        froms, urls = [], []
        for ln in sorted(groups.keys()):
            nm = alias.get(line_names[ln - 1], line_names[ln - 1]) if ln - 1 < len(line_names) else ""
            froms.append(nm or ("线路%d" % ln))
            urls.append("#".join(groups[ln]))

        mrem = re.search(r'(全\d+集|更新至[^<\s]{1,12})', html)
        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": meta("og:image"),
            "vod_content": self._clean(meta("og:description")),
            "vod_actor": field("主演"),
            "vod_director": field("导演"),
            "vod_area": field("地区"),
            "vod_year": "",
            "type_name": field("类型"),
            "vod_remarks": self._clean(mrem.group(1)) if mrem else "",
            "vod_play_from": "$$$".join(froms),
            "vod_play_url": "$$$".join(urls),
        }

    # ================= 播放（复现站点 WASM 签名） =================

    def _enc_k(self, token):
        """k = url-safe-base64( token XOR 循环密钥 )"""
        if not token:
            return ""
        key = (self.SECRET * (len(token) // len(self.SECRET) + 1))[:len(token)]
        raw = bytes(a ^ b for a, b in zip(token.encode(), key.encode()))
        return base64.urlsafe_b64encode(raw).decode()

    def _sign(self, dataid, vhash, ts):
        """s = HMAC-SHA256(key = vhash, msg = '{dataid}:{ts}:{vhash}') 的前 16 字节 hex"""
        msg = "%s:%d:%s" % (dataid, ts, vhash)
        return hmac.new(vhash.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]

    @staticmethod
    def _pick_token(html):
        m = re.search(r"userlink:\s*'([^']+)'", html) or re.search(r'userlink:\s*"([^"]+)"', html)
        tok = m.group(1).strip() if m else ""
        return tok if len(tok) > 8 and tok != "0" else ""

    def _player_url(self, dataid, vhash, token):
        ts = int(time.time() * 1000)
        return "%s/video/play?p=%s&v=%s&q=1080&s=%s&t=%d&k=%s" % (
            self.host, dataid, vhash, self._sign(dataid, vhash, ts), ts, self._enc_k(token))

    def playerContent(self, flag, id, vipFlags):
        raw = (id or "").strip()
        if "|" in raw:
            vhash, dataid = raw.split("|", 1)
        else:
            vhash, dataid = raw, ""
        vhash = vhash.strip().strip("/").split("/")[-1]
        dataid = dataid.strip()
        page_url = "%s/play/%s" % (self.host, vhash)
        fallback = {"parse": 1, "url": page_url, "header": {"User-Agent": self.UA}}

        if not vhash:
            return fallback

        # 令牌是「页面级」的（服务端每次渲染随机注入），也可能短时效 → 失败就重抓换一个再试
        for attempt in (0, 1):
            token = self._tok if (self._tok and time.time() - self._tok_ts < self.TOKEN_TTL) else ""
            if not token or not dataid:
                html = self._text(page_url, referer=self.host + "/")
                if not token:
                    token = self._pick_token(html) or token
                    if token:
                        self._tok, self._tok_ts = token, time.time()
                if not dataid and html:
                    m = (re.search(r'href="/play/' + re.escape(vhash) + r'"[^>]*?dataid="(\d+)"', html)
                         or re.search(r'dataid="(\d+)"(?:(?!</a>).)*?href="/play/' + re.escape(vhash) + r'"',
                                      html, re.S))
                    dataid = m.group(1) if m else ""
            if not (token and dataid):
                return fallback

            code, real, msg = self._play(dataid, vhash, token, page_url)
            if real:
                return {"parse": 0, "url": real,
                        "header": {"User-Agent": self.UA, "Referer": self.host + "/"}}
            self._tok, self._tok_ts = "", 0.0
            if attempt == 0 and not self._is_vip(msg):
                time.sleep(0.3)         # 令牌可能已失效 → 重抓一个再试
                continue
            break
        return fallback

    @staticmethod
    def _is_vip(msg):
        """站点会员限制：重试无意义，直接兜底。"""
        m = msg or ""
        return ("VIP" in m) or ("会员" in m) or ("登录" in m)

    def _play(self, dataid, vhash, token, referer):
        """返回 (业务 code, 直链, message)。"""
        r = self._req(self._player_url(dataid, vhash, token), referer=referer)
        if r is None:
            return 0, "", ""
        try:
            body = r.text or ""
        except Exception:
            try:
                body = (r.content or b"").decode("utf-8", "ignore")
            except Exception:
                body = ""
        if not body:
            return 0, "", ""
        try:
            d = json.loads(body)
        except Exception:
            return 0, "", ""
        code = d.get("code") or 0
        msg = d.get("message") or ""
        if code != 200:
            return code, "", msg
        urls = ((d.get("data") or {}).get("quality_urls") or [])
        for q in urls:                      # 先取免费清晰度
            url = str(q.get("url") or "")
            if url.startswith("http") and not q.get("locked") and not q.get("isvip"):
                return code, url, msg
        for q in urls:                      # 再退一步：任何可用直链
            url = str(q.get("url") or "")
            if url.startswith("http"):
                return code, url, msg
        return code, "", msg

    # ================= 本地代理（源站 m3u8 无需代理，保留空实现） =================

    def localProxy(self, param):
        return None
