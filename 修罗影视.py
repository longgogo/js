# coding=utf-8
# 修罗影视（雪落影视 v.xl01.eu.cc）TVBox Python 源
# 链路：列表/详情走 SSR HTML；播放走 /lines 签名接口 → CDN blob(前3354字节头+zlib) → localProxy 还原 m3u8
# 换域名：挂载配置里 ext 传新域名，如 {"key":"xl","name":"修罗影视","type":3,"api":"修罗影视.py","ext":"https://新域名"}
import re
import json
import time
import zlib
import base64
import random
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request
import http.cookiejar

try:
    from base.spider import Spider
except Exception:
    class Spider(object):
        pass

try:
    from Crypto.Cipher import AES as _AES
except Exception:
    _AES = None  # 走纯 Python AES 兜底


# ---------------------------------------------------------------- 纯 Python AES-128-ECB 兜底
_SBOX = None


def _init_aes_tables():
    global _SBOX
    if _SBOX is not None:
        return
    sbox = [0] * 256
    p = 1
    q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    _SBOX = sbox


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _aes_ecb_encrypt(key, data):
    """AES-128 ECB 加密（仅用于本站 16 字节 key + PKCS7 明文）。"""
    _init_aes_tables()

    def expand_key(k):
        w = [list(k[i:i + 4]) for i in range(0, 16, 4)]
        rcon = 1
        for i in range(4, 44):
            t = list(w[i - 1])
            if i % 4 == 0:
                t = t[1:] + t[:1]
                t = [_SBOX[b] for b in t]
                t[0] ^= rcon
                rcon = _xtime(rcon)
            w.append([w[i - 4][j] ^ t[j] for j in range(4)])
        return w

    def add_round(s, w, r):
        for c in range(4):
            for ro in range(4):
                s[ro][c] ^= w[r * 4 + c][ro]

    def sub_shift(s):
        for ro in range(4):
            s[ro] = [_SBOX[b] for b in s[ro]]
        for ro in range(4):
            s[ro] = s[ro][ro:] + s[ro][:ro]

    def mix(s):
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = _xtime(a[0]) ^ (_xtime(a[1]) ^ a[1]) ^ a[2] ^ a[3]
            s[1][c] = a[0] ^ _xtime(a[1]) ^ (_xtime(a[2]) ^ a[2]) ^ a[3]
            s[2][c] = a[0] ^ a[1] ^ _xtime(a[2]) ^ (_xtime(a[3]) ^ a[3])
            s[3][c] = (_xtime(a[0]) ^ a[0]) ^ a[1] ^ a[2] ^ _xtime(a[3])

    w = expand_key(key)
    pad = 16 - len(data) % 16
    data = data + bytes([pad]) * pad
    out = b""
    for off in range(0, len(data), 16):
        blk = data[off:off + 16]
        s = [[blk[r + 4 * c] for c in range(4)] for r in range(4)]
        add_round(s, w, 0)
        for rnd in range(1, 11):
            sub_shift(s)
            if rnd != 10:
                mix(s)
            add_round(s, w, rnd)
        out += bytes(s[r][c] for c in range(4) for r in range(4))
    return out


def _sg(pid, t):
    """站点签名：md5(pid-t) 前16位作 key，AES-128-ECB 加密明文 pid-t，密文转大写 HEX。"""
    plain = ("%s-%s" % (pid, t)).encode("utf-8")
    key = __import__("hashlib").md5(plain).hexdigest()[:16].encode("utf-8")
    if _AES is not None:
        c = _AES.new(key, _AES.MODE_ECB)
        pad = 16 - len(plain) % 16
        return c.encrypt(plain + bytes([pad]) * pad).hex().upper()
    return _aes_ecb_encrypt(key, plain).hex().upper()


# 模块级缓存：部分内核会在不同调用间重建 Spider 实例，缓存必须放模块级才能跨实例命中
CH_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
_LINES_CACHE = {}  # pid -> (expire_epoch, lines_data, cookie_str)
_PLAY_CACHE = {}   # 播放页路径 -> (expire_epoch, m3u8_text)
_PID_CACHE = {}    # 播放页路径 -> pid（详情页预热产物，免二次取播放页）
_INFLIGHT = {}     # 播放页路径 -> threading.Thread（后台预取去重）


class Spider(Spider):

    def getName(self):
        return "修罗影视"

    def init(self, extend=""):
        host = ""
        try:
            if extend:
                if isinstance(extend, dict):
                    host = (extend.get("host") or "").strip()
                else:
                    ext = str(extend).strip()
                    if ext.startswith("http"):
                        host = ext
                    else:
                        cfg = json.loads(ext)
                        host = (cfg.get("host") or "").strip()
        except Exception:
            host = ""
        if not host:
            host = "https://v.xl01.eu.cc"
        self.host = host.rstrip("/")
        self._lines_cache = {}
        self._jar = http.cookiejar.CookieJar()

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    UA = "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36"

    # ------------------------------------------------ 通用请求
    def _req(self, url, headers=None, timeout=15, allow_redirects=True):
        h = {"User-Agent": self.UA, "Referer": self.host + "/"}
        h.update(headers or {})
        try:
            return self.fetch(url, headers=h, timeout=timeout, allow_redirects=allow_redirects)
        except TypeError:
            try:
                return self.fetch(url, headers=h)
            except Exception:
                return None
        except Exception:
            return None

    def _get(self, path):
        r = self._req(self.host + path)
        txt = r.text if r is not None else ""
        if not txt:
            time.sleep(0.6)
            r = self._req(self.host + path)
            txt = r.text if r is not None else ""
        return txt

    # ------------------------------------------------ 列表解析
    _CARD = re.compile(
        r'(?s)<div class="movie-card">\s*<a class="card-img"[^>]*?title="([^"]*)"[^>]*?href="([^"]*)"[^>]*>'
        r'.*?data-src="([^"]*)".*?(?:episode-badge">\s*([^<]*?)\s*</div>)?.*?</a>\s*'
        r'<div class="card-info">\s*<h4>(.*?)</h4>')

    def _parse_cards(self, html):
        videos, seen = [], set()
        for m in self._CARD.finditer(html):
            title, href, pic, badge, name = m.groups()
            if not href or href in seen:
                continue
            seen.add(href)
            videos.append({
                "vod_id": href,
                "vod_name": (name or title or "").strip(),
                "vod_pic": pic,
                "vod_remarks": (badge or "").strip(),
            })
        return videos

    # ------------------------------------------------ 五个数据接口
    def homeContent(self, filter):
        cates = [
            {"type_id": "movie", "type_name": "电影"},
            {"type_id": "tv", "type_name": "剧集"},
            {"type_id": "g_dongzuo", "type_name": "动作"},
            {"type_id": "g_aiqing", "type_name": "爱情"},
            {"type_id": "g_xiju", "type_name": "喜剧"},
            {"type_id": "g_kehuan", "type_name": "科幻"},
            {"type_id": "g_donghua", "type_name": "动画"},
            {"type_id": "g_juqing", "type_name": "剧情"},
            {"type_id": "g_xuanyi", "type_name": "悬疑"},
            {"type_id": "g_kongbu", "type_name": "恐怖"},
            {"type_id": "g_zhanzheng", "type_name": "战争"},
            {"type_id": "g_wuxia", "type_name": "武侠"},
            {"type_id": "g_fanzui", "type_name": "犯罪"},
            {"type_id": "g_guzhuang", "type_name": "古装"},
            {"type_id": "g_zongyi", "type_name": "综艺"},
            {"type_id": "g_duanju", "type_name": "短剧"},
            {"type_id": "g_meiju", "type_name": "美剧"},
            {"type_id": "g_hanju", "type_name": "韩剧"},
            {"type_id": "g_guoju", "type_name": "国产剧"},
            {"type_id": "g_riju", "type_name": "日剧"},
            {"type_id": "g_yingju", "type_name": "英剧"},
            {"type_id": "g_gangtaiju", "type_name": "港台剧"},
        ]
        areas = ["中国大陆", "中国香港", "中国台湾", "美国", "英国", "日本", "韩国", "法国",
                 "印度", "德国", "西班牙", "意大利", "澳大利亚", "加拿大", "俄罗斯"]
        years = [str(y) for y in range(2026, 2001, -1)]
        result = {"class": cates, "filters": {}}
        for c in cates[:2]:
            result["filters"][c["type_id"]] = [
                {"key": "area", "name": "地区",
                 "value": [{"n": a, "v": a} for a in areas]},
                {"key": "year", "name": "年份",
                 "value": [{"n": y, "v": y} for y in years]},
                {"key": "order", "name": "排序",
                 "value": [{"n": "更新时间", "v": "0"}, {"n": "豆瓣评分", "v": "1"}]},
            ]
        return result

    def homeVideoContent(self):
        html = self._get("/")
        return {"list": self._parse_cards(html)}

    def categoryContent(self, tid, pg, filter, extend):
        extend = extend or {}
        pg = int(pg) if str(pg).isdigit() else 1
        if tid.startswith("g_"):
            path = "/s/%s/%d" % (tid[2:], pg)
        else:
            t = "0" if tid == "movie" else "1"
            qs = ["type=" + t]
            for k in ("area", "year", "order"):
                v = str(extend.get(k, "") or "").strip()
                if v and v not in ("不限", "0页"):
                    qs.append("%s=%s" % (k, urllib.parse.quote(v)))
            path = "/s/all/%d?%s" % (pg, "&".join(qs))
        html = self._get(path)
        return {
            "list": self._parse_cards(html),
            "page": pg,
            "pagecount": 9999,
            "limit": 24,
            "total": 999999,
        }

    def detailContent(self, ids):
        html = self._get(ids[0])
        name = ""
        mh = re.search(r'<h1 class="movie-title">(.*?)</h1>', html)
        if mh:
            name = mh.group(1).strip()
        year = ""
        my = re.search(r'<h1 class="movie-title">.*?\((\d{4})\)', html)
        if my:
            year = my.group(1)
        pic = ""
        mp = re.search(r'<div class="movie-poster">\s*<img src="([^"]+)"', html)
        if mp:
            pic = mp.group(1)
        rating = ""
        mr = re.search(r'score-text">\s*([\d.]+)', html)
        if mr:
            rating = mr.group(1)
        info = {}
        for m in re.finditer(r'<div class="info-item"><span class="info-label">([^<]+)：</span>(.*?)</div>', html, re.S):
            label = m.group(1).strip()
            val = re.sub(r"<[^>]+>", " ", m.group(2))
            val = re.sub(r"\s+", " ", val).strip()
            if val:
                info[label] = val
        desc = ""
        md = re.search(r'<div class="desc">(.*?)</div>', html, re.S)
        if md:
            desc = re.sub(r"<br\s*/?>", "\n", md.group(1))
            desc = re.sub(r"<[^>]+>", "", desc).strip()
        eps = []
        for m in re.finditer(r'<a class="play-item"[^>]*href="([^"]*/play/[^"]+)"[^>]*>\s*([^<]+?)\s*</a>', html):
            eps.append((m.group(2).strip(), m.group(1)))
        play_url = "#".join("%s$%s" % (n, u) for n, u in eps)
        remarks = info.get("别名", "")
        if rating:
            remarks = (rating + "分 " + remarks).strip()
        video = {
            "vod_id": ids[0],
            "vod_name": name,
            "vod_pic": pic,
            "type_name": info.get("类型", ""),
            "vod_year": year,
            "vod_area": info.get("制片国家", ""),
            "vod_actor": info.get("主演", ""),
            "vod_director": " ".join(x for x in (info.get("导演", ""), info.get("编剧", "")) if x),
            "vod_remarks": remarks,
            "vod_content": desc,
            "vod_play_from": "雪落影视",
            "vod_play_url": play_url,
        }
        try:
            self._prefetch_detail(html)
        except Exception:
            pass
        return {"list": [video]}

    def _prefetch_detail(self, html):
        """详情页后台预热：取前 10 集播放页的 pid 并预请求 /lines。
        用户在详情页停留的几秒里把点播放后的链路缩短到 blob+验真 2 个请求。"""
        eps = re.findall(r'<a class="play-item"[^>]*href="([^"]*/play/[^"]+)"', html)
        if not eps:
            return

        def work():
            for pth in eps[:10]:
                try:
                    if _PID_CACHE.get(pth):
                        continue
                    phtml = self._get(pth)
                    mp = re.search(r"var\s+pid\s*=\s*(\d+)", phtml)
                    if not mp:
                        continue
                    _PID_CACHE[pth] = mp.group(1)
                    try:
                        self._get_lines(mp.group(1))
                    except Exception:
                        pass
                    time.sleep(0.3)
                except Exception:
                    pass

        th = threading.Thread(target=work)
        th.daemon = True
        th.start()

    def searchContent(self, key, quick, pg=1):
        # 站点限制：30 分钟内首次搜索需图形验证码，无法自动化 → 如实返回空
        if pg > 1 or not key:
            return {"list": [], "page": pg}
        try:
            html = self._get("/search/" + urllib.parse.quote(key))
            if "verifyCode" in html or "xl-code-wrap" in html:
                return {"list": [], "page": pg}
            return {"list": self._parse_cards(html), "page": pg}
        except Exception:
            return {"list": [], "page": pg}

    def playerContent(self, flag, id, vipFlags):
        # 只启动后台预取、立即返回：playerContent 阻塞过久会被内核判"获取播放信息错误"
        try:
            self._kick_resolve(id)
        except Exception:
            pass
        token = base64.urlsafe_b64encode(id.encode("utf-8")).decode("ascii")
        url = self.getProxyUrl() + "&url=" + token + "&type=m3u8"
        return {
            "parse": 0,
            "url": url,
            "header": {"User-Agent": self.UA, "Referer": self.host + "/"},
        }

    # ------------------------------------------------ 播放链路：lines 签名 → blob 还原
    # 全部走内核自带 self.fetch（OkHttp）：Android 内嵌 Python 的 urllib 证书链不可靠，
    # 且浏览功能已证明 self.fetch 在盒子上可用。
    def _fetch_via_base(self, url, headers=None, timeout=15, range_end=None):
        """返回 (bytes, set_cookie_str)。"""
        h = {"User-Agent": CH_UA, "Referer": self.host + "/"}
        if headers:
            h.update(headers)
        if range_end is not None:
            h["Range"] = "bytes=0-%d" % range_end
        try:
            try:
                r = self.fetch(url, headers=h, timeout=timeout)
            except TypeError:
                r = self.fetch(url, headers=h)
            sc = ""
            try:
                sc = r.headers.get("Set-Cookie") or ""
            except Exception:
                try:
                    sc = r.headers["Set-Cookie"] or ""
                except Exception:
                    sc = ""
            body = r.content
            if range_end is not None and body:
                body = body[:range_end + 1]
            return body, sc
        except Exception:
            return None, ""

    def _get_lines(self, pid):
        now = time.time()
        cached = _LINES_CACHE.get(str(pid))
        if cached and now < cached[0]:
            return cached[1], cached[2]
        t = str(int(time.time() * 1000))
        url = "%s/lines?t=%s&sg=%s&pid=%s" % (self.host, t, _sg(pid, t), pid)
        raw, sc = self._fetch_via_base(url, {"X-Requested-With": "XMLHttpRequest"}, timeout=12)
        if not raw:
            return None, ""
        try:
            d = json.loads(raw.decode("utf-8", "ignore"))
        except Exception:
            return None, ""
        if d.get("code") != 0:
            return None, ""
        ck = ""
        m = re.search(r"JSESSIONID=([^;,\s]+)", sc or "")
        if m:
            ck = "JSESSIONID=" + m.group(1)
        _LINES_CACHE[str(pid)] = (now + 900, d.get("data") or {}, ck)
        return d.get("data") or {}, ck

    def _decode_blob(self, raw):
        """blob 三种形态：PNG 伪装(前3354头+zlib) / 明文 m3u8 / 其它(失败)。"""
        if not raw or len(raw) < 4000:
            return None
        if raw[:5] == b"#EXTM":
            return raw.decode("utf-8", "ignore")
        if raw[:4] == b"\x89PNG":
            try:
                return zlib.decompress(raw[3354:], 47).decode("utf-8", "ignore")
            except Exception:
                try:
                    return zlib.decompress(raw[3354:]).decode("utf-8", "ignore")
                except Exception:
                    return None
        return None

    def _prefixes_for(self, blob_url):
        """分片绝对前缀候选：站点域名优先（盒子侧已验证可达），CDN 兜底。"""
        return [self.host + "/", "https://vod.xl01.me/",
                "https://vod.xl01.me/hls/" if ("2014-us" in blob_url or "ac5634-us" in blob_url)
                else "https://vod.xl01.me/"]

    def _rewrite_m3u8(self, text, prefix):
        lines = text.strip().split("\n")
        out = []
        for ln in lines:
            ln = ln.strip()
            if not ln or ln.startswith("#") or ln.startswith("http"):
                out.append(ln)
            else:
                out.append(prefix + ln.lstrip("/"))
        return "\n".join(out)

    def _seg_check(self, text, prefix):
        """Range 取首分片前 376 字节判型：'ts'=健康 / 'png'=伪装废料线路 / 'other'=该前缀不可用。"""
        try:
            seg = None
            for ln in text.split("\n"):
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    seg = ln
                    break
            if not seg:
                return "other"
            u = seg if seg.startswith("http") else prefix + seg.lstrip("/")
            raw = self._fetch_via_base(u, timeout=10, range_end=375)[0]
            if not raw:
                return "other"
            if raw[:4] == b"\x89PNG":
                return "png"
            return "ts" if raw[0] == 0x47 else "other"
        except Exception:
            return "other"

    _BLOB_HOSTS = ("www.bde4.cc", "vod.xlys01.com", "vod.xlys.cc.ua")

    def _check_line(self, blob_url, ck):
        """取 blob → 解码 → 验真。返回 (可用m3u8文本 or None, 已解码文本 or None)。"""
        h = {"Referer": self.host + "/"}
        if ck:
            h["Cookie"] = ck
        for u in blob_url:
            try:
                raw, _ = self._fetch_via_base(u, h, timeout=12)
                txt = self._decode_blob(raw)
                if not txt:
                    continue
                for pre in self._prefixes_for(u):
                    st = self._seg_check(txt, pre)
                    if st == "ts":
                        return self._rewrite_m3u8(txt, pre), txt
                    if st == "png":
                        break  # 分片本身就是 PNG 废料，换前缀也没用
                return None, txt
            except Exception:
                continue
        return None, None

    def _fetch_m3u8_text(self, pid):
        data, ck = self._get_lines(pid)
        if not data:
            return None
        dom = self.host.split("//")[-1]
        cands = []
        if data.get("m3u8"):
            cands.append(data["m3u8"].split("#")[0])
        if data.get("m3u8_2"):
            for u in data["m3u8_2"].split(","):
                u = u.split("#")[0]
                if "DFD45E4E4144454C2EFF2EB0D780743BA" in u or "644B785B38CAFA85D85AF61944F6581" in u:
                    continue
                cands.append(u)
        # blob 统一改走站点域名（盒子侧唯一确认可达的入口），原始 host 作备选
        pairs = []
        seen = set()
        for u in cands:
            if not u:
                continue
            u_site = u
            for bh in self._BLOB_HOSTS:
                if bh in u_site:
                    u_site = u_site.replace(bh, dom)
            key = u_site.split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            pairs.append((u_site,) if u_site == u else (u_site, u))
        first_txt = None
        if pairs:
            ex = ThreadPoolExecutor(max_workers=min(4, len(pairs)))
            try:
                futs = [ex.submit(self._check_line, pr, ck) for pr in pairs]
                for f in as_completed(futs):
                    try:
                        ok_txt, decoded = f.result()
                    except Exception:
                        continue
                    if decoded and first_txt is None:
                        first_txt = self._rewrite_m3u8(decoded, self.host + "/")
                    if ok_txt:
                        try:
                            ex.shutdown(wait=False)
                        except Exception:
                            pass
                        return ok_txt
            finally:
                try:
                    ex.shutdown(wait=False)
                except Exception:
                    pass
        # 兜底：/god?type=1（POST 走 base.fetch，不支持则跳过）
        try:
            now = str(int(time.time() * 1000))
            body = urllib.parse.urlencode({"t": now, "sg": _sg(pid, now), "verifyCode": "888"}).encode("utf-8")
            r = None
            try:
                r = self.fetch("%s/god/%s?type=1" % (self.host, pid), data=body, timeout=15,
                               headers={"User-Agent": CH_UA, "X-Requested-With": "XMLHttpRequest",
                                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                        "Referer": self.host + "/"},
                               allow_redirects=True)
            except TypeError:
                pass
            if r is not None:
                gu = (json.loads(r.content.decode("utf-8", "ignore")) or {}).get("url")
                if gu:
                    ok_txt, decoded = self._check_line((gu,), ck)
                    if ok_txt:
                        return ok_txt
                    if decoded:
                        first_txt = first_txt or self._rewrite_m3u8(decoded, self.host + "/")
        except Exception:
            pass
        return first_txt  # 验真全失败时退而求其次，仍给播放器一个机会

    def _resolve_m3u8(self, path):
        """播放页路径 → 可直出 m3u8 文本（带模块级缓存；失败短缓存防打爆）。"""
        now = time.time()
        hit = _PLAY_CACHE.get(path)
        if hit and now < hit[0]:
            return hit[1]
        txt = None
        try:
            pid = _PID_CACHE.get(path)
            if not pid:
                html = self._get(path)
                mp = re.search(r"var\s+pid\s*=\s*(\d+)", html)
                if mp:
                    pid = mp.group(1)
                    _PID_CACHE[path] = pid
            if pid:
                txt = self._fetch_m3u8_text(pid)
        except Exception:
            txt = None
        _PLAY_CACHE[path] = (now + (600 if txt else 20), txt)
        return txt

    def _kick_resolve(self, path):
        """后台预取：playerContent 立即返回，播放器请求 localProxy 时大概率已就绪。"""
        now = time.time()
        hit = _PLAY_CACHE.get(path)
        if hit and (hit[1] is not None or now < hit[0]):
            return
        t = _INFLIGHT.get(path)
        if t is not None and t.is_alive():
            return

        def work():
            try:
                self._resolve_m3u8(path)
            except Exception:
                pass

        th = threading.Thread(target=work)
        th.daemon = True
        _INFLIGHT[path] = th
        th.start()

    def localProxy(self, param):
        try:
            path = ""
            raw = param.get("url") or ""
            if raw:
                raw = raw.replace(" ", "+")  # 防部分内核把 + 解码成空格
                try:
                    path = base64.urlsafe_b64decode(raw).decode("utf-8", "ignore")
                except Exception:
                    try:
                        path = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "ignore")
                    except Exception:
                        path = ""
            if not path:
                path = urllib.parse.unquote(param.get("path", ""))
            if not path or not path.startswith("/"):
                return [200, "text/plain", "bad path"]
            txt = None
            now = time.time()
            hit = _PLAY_CACHE.get(path)
            if hit and now < hit[0]:
                txt = hit[1]
            if txt is None:
                t = _INFLIGHT.get(path)
                if t is not None and t.is_alive():
                    t.join(10)  # 等后台预取收尾
                hit = _PLAY_CACHE.get(path)
                if hit and time.time() < hit[0]:
                    txt = hit[1]
            if txt is None:
                txt = self._resolve_m3u8(path)
            if not txt:
                return [200, "text/plain", "#EXTM3U"]
            return [200, "application/vnd.apple.mpegurl", txt]
        except Exception as e:
            try:
                self.log("xl localProxy err: %s" % e)
            except Exception:
                pass
            return [200, "text/plain", "err"]
