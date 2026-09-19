# coding=utf-8
"""
雪落影视 (XLYS) —— TVBox Python 蜘蛛源 (DRPY 格式)
================================================
站点 : 雪落影视   https://v.xl01.eu.cc
说明 :
  1. 播放链路已逆向：详情页 -> 播放页取内部 pid -> POST /god/{pid}?type=1
     提交 AES 签名 sg + 万能校验码 888 -> 返回直链 MP4（支持 Range 拖动）。
  2. 本文件不依赖 pycryptodome / requests，AES 为内置纯 Python 实现，
     可直接在 TVBox 的 py 运行环境中使用。
  3. 搜索受站点风控限制：同一 IP 每 30 分钟首次搜索需要图片验证码，
     纯 py 无法识别，此时搜索会返回空并给出提示（浏览/播放不受影响）。
  4. 若主域名被墙，初始化时自动探测并切换到可用镜像域名；
     播放前还会对 CDN 直链域名做可用性探测，自动避开超时域名。
================================================
"""

import json
import re
import time
import hashlib
import urllib.parse
import urllib.request
import urllib.error
import http.cookiejar
import ssl

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    _create_unverified_https_context = None

# --------------------------------------------------------------------------
# 站点配置
# --------------------------------------------------------------------------
HOSTS = [
    'https://v.xl01.eu.cc',     # 主域名（用户给定）
    'https://v.xl.in.ua',       # 备用镜像
    'https://v.xl01.cc.ua',     # 备用镜像
]

UA = ('Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Mobile Safari/537.36')

# 分类（拼音 slug -> 中文名）
CATEGORIES = {
    'dongzuo': '动作', 'aiqing': '爱情', 'xiju': '喜剧', 'kehuan': '科幻',
    'kongbu': '恐怖', 'zhanzheng': '战争', 'wuxia': '武侠', 'mohuan': '魔幻',
    'juqing': '剧情', 'donghua': '动画', 'jingsong': '惊悚', '3D': '3D',
    'zainan': '灾难', 'xuanyi': '悬疑', 'jingfei': '警匪', 'wenyi': '文艺',
    'qingchun': '青春', 'maoxian': '冒险', 'fanzui': '犯罪', 'jilu': '纪录',
    'guzhuang': '古装', 'qihuan': '奇幻', 'guoyu': '国语', 'zongyi': '综艺',
    'lishi': '历史', 'yundong': '运动', 'yuanchuang': '原创压制',
    'meiju': '美剧', 'hanju': '韩剧', 'guoju': '国产电视剧', 'riju': '日剧',
    'yingju': '英剧', 'deju': '德剧', 'eju': '俄剧', 'baju': '巴剧',
    'jiaju': '加剧', 'spanish': '西剧', 'yidaliju': '意大利剧',
    'taiju': '泰剧', 'gangtaiju': '港台剧', 'faju': '法剧', 'aoju': '澳剧',
    'duanju': '短剧',
}

# CDN 候选域名（2026-09 实测可靠性排序；播放时会逐个探测，选第一个能拉到数据的）
CDN_CANDIDATES = [
    'https://lf16-anyweb.anyweb.space',
    'http://lf77-geckocdn.bytegecko-i18n.com',
    'https://p16-hera-sign-va.ibyteimg.com',
]
_TOS_BUCKETS = ('tos-alisg-i-0000', 'tos-alisg-v-0000', 'tos-maliva-o-0000-us')

# 页面有效性标记：用于识别真页面，防止把 Cloudflare 挑战页当正常页面
_PAGE_MARKERS = ('movie-card', 'movie-title', 'xlplayer', 'var pid',
                 'xl-code-wrap', '<title')


# --------------------------------------------------------------------------
# 纯 Python AES-128-ECB（无第三方依赖）
# --------------------------------------------------------------------------
def _init_aes_tables():
    sbox = [0] * 256
    p = q = 1
    while True:
        p = (p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)) & 0xFF
        q ^= (q << 1) & 0xFF
        q ^= (q << 2) & 0xFF
        q ^= (q << 4) & 0xFF
        if q & 0x80:
            q ^= 0x09
        q &= 0xFF
        x = (q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6))
             ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4)))
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox

_SBOX = _init_aes_tables()
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _expand_key(key):
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= _RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def _encrypt_block(block, w):
    s = [block[i] for i in range(16)]

    def add_round_key(rnd):
        for c in range(4):
            for r in range(4):
                s[r + 4 * c] ^= w[rnd * 4 + c][r]

    add_round_key(0)
    for rnd in range(1, 10):
        s = [_SBOX[v] for v in s]
        ns = list(s)
        for r in range(1, 4):
            for c in range(4):
                ns[r + 4 * c] = s[r + 4 * ((c + r) % 4)]
        s = ns
        ns = list(s)
        for c in range(4):
            a = s[0 + 4 * c]; b = s[1 + 4 * c]; d = s[2 + 4 * c]; e = s[3 + 4 * c]
            xt = lambda v: (v << 1) ^ (0x1B if v & 0x80 else 0)
            ns[0 + 4 * c] = xt(a) ^ (xt(b) ^ b) ^ d ^ e
            ns[1 + 4 * c] = a ^ xt(b) ^ (xt(d) ^ d) ^ e
            ns[2 + 4 * c] = a ^ b ^ xt(d) ^ (xt(e) ^ e)
            ns[3 + 4 * c] = (xt(a) ^ a) ^ b ^ d ^ xt(e)
        s = [v & 0xFF for v in ns]
        add_round_key(rnd)
    s = [_SBOX[v] for v in s]
    ns = list(s)
    for r in range(1, 4):
        for c in range(4):
            ns[r + 4 * c] = s[r + 4 * ((c + r) % 4)]
    s = ns
    add_round_key(10)
    return bytes(s)


def aes_ecb_encrypt(key16, data):
    w = _expand_key(key16)
    out = b''
    for i in range(0, len(data), 16):
        out += _encrypt_block(data[i:i + 16], w)
    return out


def pkcs7_pad(b):
    p = 16 - (len(b) % 16)
    return b + bytes([p]) * p


def make_sg(pid, ts):
    """生成 /god 接口签名 sg = AES-ECB(md5(pid-ts)[:16], 'pid-ts') 的十六进制大写"""
    raw = ('%s-%d' % (pid, ts)).encode('utf-8')
    key = hashlib.md5(raw).hexdigest()[:16].encode('utf-8')
    return aes_ecb_encrypt(key, pkcs7_pad(raw)).hex().upper()


# --------------------------------------------------------------------------
# 蜘蛛主体
# --------------------------------------------------------------------------
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object


class Spider(_BaseSpider):

    def getName(self):
        return '雪落影视'

    # ---------------- 初始化 ----------------
    def init(self, extend=''):
        self.host = HOSTS[0]
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))
        self.opener.addheaders = [('User-Agent', UA)]
        # 允许通过 extend 传入 json 覆盖域名，例如 {"host":"https://v.xl.in.ua"}
        if extend:
            try:
                ext = json.loads(extend)
                if isinstance(ext, dict) and ext.get('host'):
                    self.host = str(ext['host']).rstrip('/')
                    HOSTS.insert(0, self.host)
            except Exception:
                if extend.startswith('http'):
                    self.host = extend.rstrip('/')
                    HOSTS.insert(0, self.host)
        # 初始化时快速探测域名，主域名被墙时立即落到可用镜像，
        # 避免首次加载逐个撞死域名导致长时间无响应
        for h in HOSTS:
            if self._probe_host(h):
                self.host = h
                break
        return self.host

    def _probe_host(self, h, timeout=6):
        try:
            req = urllib.request.Request(h + '/', headers={'User-Agent': UA})
            with self.opener.open(req, timeout=timeout) as r:
                html = r.read().decode('utf-8', 'ignore')
            if 'cf-chl' in html or 'Just a moment' in html:
                return False
            return ('movie-card' in html) or ('xlplayer' in html) \
                or len(html) > 20000
        except Exception:
            return False

    # ---------------- HTTP ----------------
    def _raw(self, url, data=None, referer=None, timeout=20):
        headers = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        if referer:
            headers['Referer'] = referer
        if data is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            headers['X-Requested-With'] = 'XMLHttpRequest'
            headers['Accept'] = 'application/json, text/javascript, */*; q=0.01'
            body = data.encode('utf-8')
        else:
            body = None
        req = urllib.request.Request(url, data=body, headers=headers)
        with self.opener.open(req, timeout=timeout) as r:
            return r.read().decode('utf-8', 'ignore')

    def _get(self, url, referer=None, timeout=20, tries=3):
        """url 可为绝对路径('/xxx.htm')或完整 URL；
        站点偶发限流会返回极短的占位页，这里做重试 + 长度校验，并自动切换域名"""
        if url.startswith('http'):
            for i in range(tries):
                try:
                    return self._raw(url, None, referer, timeout)
                except Exception as e:
                    if i == tries - 1:
                        raise e
                    time.sleep(0.5)
            return ''
        hosts = [self.host] + [h for h in HOSTS if h != self.host]
        err = None
        for h in hosts:
            for i in range(tries):
                try:
                    html = self._raw(h + url, None, referer or (h + '/'), timeout)
                    if self._looks_valid(html):
                        if h != self.host:
                            self.host = h
                        return html
                except Exception as e:
                    err = e
                time.sleep(0.6)
        if err:
            raise err
        return ''

    def _looks_valid(self, html):
        """校验响应是站点真实页面，而不是 CF 挑战页 / 空占位页"""
        if not html or len(html) < 1000:
            return False
        if 'cf-chl' in html or 'Just a moment' in html:
            return False
        return any(m in html for m in _PAGE_MARKERS)

    def _post(self, url, data, referer=None, timeout=20):
        return self._raw(url, data, referer, timeout)

    # ---------------- 首页 ----------------
    def homeContent(self, filter):
        result = {}
        classes = []
        for slug, name in CATEGORIES.items():
            classes.append({'type_name': name, 'type_id': slug})
        result['class'] = classes
        return result

    def homeVideoContent(self):
        try:
            html = self._get('/')
        except Exception:
            return {'list': []}
        return {'list': self._parse_cards(html)}

    # ---------------- 分类 ----------------
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        url = '/s/%s' % tid if pg <= 1 else '/s/%s/%d' % (tid, pg)
        try:
            html = self._get(url)
        except Exception:
            return {'list': [], 'page': pg, 'pagecount': pg, 'limit': 0, 'total': 0}
        videos = self._parse_cards(html)
        pagecount = self._pagecount(html, pg)
        return {
            'list': videos,
            'page': pg,
            'pagecount': pagecount,
            'limit': len(videos),
            'total': len(videos) * pagecount,
        }

    # ---------------- 详情 ----------------
    def detailContent(self, ids):
        did = ids[0] if isinstance(ids, list) else ids
        if did.startswith('http'):
            url = did
            vid = urllib.parse.urlparse(did).path
        else:
            vid = did if did.startswith('/') else '/' + did
            url = vid
        try:
            html = self._get(url)
        except Exception:
            return {'list': []}
        v = self._parse_detail(html, vid)
        return {'list': [v] if v else []}

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick, pg='1'):
        pg = int(pg) if str(pg).isdigit() else 1
        url = '/search/' + urllib.parse.quote(str(key))
        if pg > 1:
            url += '/' + str(pg)
        try:
            html = self._get(url)
        except Exception:
            return {'list': []}
        # 站点风控：30 分钟内首次搜索需要图片验证码
        if '需要输入验证码' in html or 'xl-code-wrap' in html:
            return {'list': []}
        return {'list': self._parse_cards(html)}

    def searchContentPage(self, key, quick, pg='1'):
        return self.searchContent(key, quick, pg)

    # ---------------- 播放 ----------------
    def playerContent(self, flag, id, vipFlags):
        result = {}
        try:
            # 1) 取播放页内部 pid
            play_url = id
            if not play_url.startswith('http'):
                play_url = (play_url if play_url.startswith('/') else '/' + play_url)
                html = self._get(play_url)
            else:
                html = self._get(play_url)
            m = re.search(r'var\s+pid\s*=\s*(\d+)', html)
            if not m:
                return {}
            pid = m.group(1)

            # 2) 计算签名，POST /god/{pid}?type=1（万能校验码 888）
            ts = int(time.time() * 1000)
            sg = make_sg(pid, ts)
            data = urllib.parse.urlencode({'t': ts, 'sg': sg, 'verifyCode': '888'})
            resp = self._post(self.host + '/god/%s?type=1' % pid, data,
                              referer=self.host + play_url)
            j = json.loads(resp)
            src = j.get('url') or ''
            if not src:
                return {}
            play = self._fix_cdn(src)

            result['parse'] = 0
            result['playUrl'] = ''
            result['url'] = play
            result['header'] = json.dumps({'User-Agent': UA, 'Referer': self.host + '/'})
            result['contentType'] = 'video/mp4'
        except Exception:
            if getattr(self, 'debug', False):
                import traceback
                traceback.print_exc()
            return {}
        return result

    # ---------------- 工具 ----------------
    def _probe_url(self, url, timeout=6):
        """对直链发一个小 Range 请求，确认该 CDN 域名当前能拉到数据"""
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA, 'Referer': self.host + '/'})
            req.add_header('Range', 'bytes=0-1023')
            with self.opener.open(req, timeout=timeout) as r:
                r.read(1024)
                return True
        except Exception:
            return False

    def _fix_cdn(self, u):
        """播放前探测 CDN 域名可用性：
        保留签名路径，逐个候选域名发 Range 探测，返回第一个能拉到数据的直链。
        （原兜底域名 p16-hera-sign-va.ibyteimg.com 已经常性超时）"""
        bucket = None
        for b in _TOS_BUCKETS:
            if b in u:
                bucket = b
                break
        if not bucket:
            return u
        i = u.find(bucket)
        j = u.rfind('/obj/', 0, i)
        path = u[j:] if j >= 0 else u[i:]
        cur = u[:j] if j > 0 else ''
        cands = []
        for c in ([cur] if cur else []) + CDN_CANDIDATES:
            if c and c not in cands:
                cands.append(c)
        for c in cands:
            url = c + path
            if self._probe_url(url):
                return url
        return cands[0] + path

    def _clean(self, s):
        if not s:
            return ''
        s = re.sub(r'<[^>]+>', '', s)
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

    def _pagecount(self, html, cur):
        nums = [int(x) for x in re.findall(r'/s/[A-Za-z0-9]+/(\d+)[;"?]', html)]
        mx = max(nums) if nums else cur
        return max(mx, cur)

    def _parse_cards(self, html):
        videos = []
        seen = set()
        for chunk in html.split('<div class="movie-card">')[1:]:
            # 服务端可能把 ;jsessionid=xxx 拼在链接后面，需要容错
            href = re.search(r'href="(/[A-Za-z0-9_]+/\d+\.htm)(?:;jsessionid=[^"]*)?"', chunk)
            if not href:
                continue
            vid = href.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            name = re.search(r'<h4>(.*?)</h4>', chunk, re.S)
            img = re.search(r'data-src="([^"]+)"', chunk)
            if not img:
                img = re.search(r'<img[^>]+src="(https?://[^"]+)"', chunk)
            remark = re.search(r'<div class="episode-badge">(.*?)</div>', chunk, re.S)
            score = re.search(r'(\d+\.\d+)\s*</div>', chunk)
            note = ''
            if remark:
                note = self._clean(remark.group(1))
            elif score:
                note = score.group(1)
            videos.append({
                'vod_id': vid,
                'vod_name': self._clean(name.group(1)) if name else '',
                'vod_pic': img.group(1) if img else '',
                'vod_remarks': note,
            })
        return videos

    def _parse_detail(self, html, vid):
        title = re.search(r'<h1 class="movie-title">(.*?)</h1>', html, re.S)
        name = self._clean(title.group(1)) if title else ''
        year = ''
        if name:
            ym = re.search(r'\((\d{4})\)', name)
            if ym:
                year = ym.group(1)
                name = name[:ym.start()].strip()

        pic = ''
        pm = re.search(r'<div class="movie-poster">\s*<img[^>]+src="([^"]+)"', html, re.S)
        if not pm:
            pm = re.search(r'--bg-img:\s*url\(([^)]+)\)', html)
        if pm:
            pic = pm.group(1)

        def info(label):
            m = re.search(r'<span class="info-label">%s：</span>(.*?)</div>' % label,
                          html, re.S)
            if not m:
                return ''
            seg = m.group(1)
            vals = re.findall(r'class="info-value"[^>]*>(.*?)</(?:a|span)>', seg, re.S)
            if not vals:
                return self._clean(seg)
            return ','.join([self._clean(v) for v in vals if self._clean(v)])

        content = ''
        cm = re.search(r'<div class="desc">(.*?)</div>', html, re.S)
        if cm:
            content = self._clean(cm.group(1))

        # 播放列表
        froms, urls = [], []
        items = re.findall(r'<a class="play-item"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                           html, re.S)
        parts = []
        for href, label in items:
            lb = self._clean(label)
            # 统一为绝对路径
            if href.startswith('http'):
                href = urllib.parse.urlparse(href).path
            parts.append('%s$%s' % (lb, href))

        if parts:
            froms.append('在线播放')
            urls.append('#'.join(parts))

        return {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': pic,
            'type_name': info('类型'),
            'vod_year': year,
            'vod_area': info('制片国家'),
            'vod_remarks': info('单集片长') or '',
            'vod_actor': info('主演'),
            'vod_director': info('导演'),
            'vod_content': content,
            'vod_play_from': '$$$'.join(froms),
            'vod_play_url': '$$$'.join(urls),
        }

    def localProxy(self, param):
        return None


if __name__ == '__main__':
    sp = Spider()
    print('name:', sp.getName())
    sp.init('')
    print('host:', sp.host)
