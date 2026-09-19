# coding=utf-8
"""
4K在线 —— TVBox Python 蜘蛛（py 源）
================================================
站点 : 4K在线   https://www.bbibb.top
站型 : 海洋CMS（SeaCMS）+ mytheme（myui 系）模板，路由如下
  首页  /
  分类  /list/?{tid}.html              翻页 /list/?{tid}-{N}.html
  详情  /detail/?{id}.html
  播放  /video/?{id}-{sid}-{nid}.html
  搜索  /search.php?searchword={kw}

★ 播放：播放页直接把直链写在 <script> 的 var now="..." 里
  （多为 https://vodcnd*.uvjtih.cn/.../index.m3u8，少数 mp4），
  无加密、无 player_data、无解析接口 —— 六条线路全部 parse=0 直出，
  不需要 TVBox 嗅探。

★ 风控：浏览 / 详情 / 播放均正常；唯独「搜索」会被站点「系统安全验证」
  （图片验证码 include/vdimgck.php）拦截。纯 py 在 TVBox 内无法识别
  图片验证码，故搜索会返回空并给出提示，浏览与播放不受影响。

★ 备用域名 klyingshi1.com 当前返回 403（已封），已加入列表，
  请求失败时自动跳过并回退到主域名。
================================================
"""

import json
import re
import time
import ssl
import urllib.parse
import urllib.request

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object


# --------------------------------------------------------------------------
# 站点配置
# --------------------------------------------------------------------------
HOSTS = [
    'https://www.bbibb.top',     # 主域名
    'https://klyingshi1.com',    # 备用（当前 403，自动跳过）
]

UA = ('Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0.0.0 Mobile Safari/537.36')

# 分类（type_id -> 中文名，取自站点导航菜单）
CATEGORIES = {
    '1': '电影', '2': '电视剧', '3': '综艺', '4': '动漫',
    '5': '动作片', '6': '爱情片', '7': '科幻片', '8': '恐怖片',
    '9': '战争片', '10': '喜剧片', '11': '纪录片', '12': '剧情片',
    '13': '大陆剧', '14': '港台剧', '15': '欧美剧', '16': '日韩剧',
    '25': '海外剧', '26': '泰国剧',
}

# 页面有效性标记：备用域返回 403 页面不含这些标记 → 自动跳过
_PAGE_MARKERS = ('myui', 'myui-vodlist', 'myui-content__list', 'var now')
_CAPTCHA_MARKERS = ('系统安全验证', '请输入正确的验证码', 'vdimgck.php')


# --------------------------------------------------------------------------
# 蜘蛛主体
# --------------------------------------------------------------------------
class Spider(_BaseSpider):

    def getName(self):
        return '4K在线'

    # ---------------- 初始化 ----------------
    def init(self, extend=''):
        self.host = HOSTS[0]
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        # 允许通过 extend 覆盖域名，例如 https://www.bbibb.top 或 {"host":"..."}
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
        # 快速探测：挑第一个含站点标记的可用域名
        for h in HOSTS:
            if self._probe_host(h):
                self.host = h
                break
        return self.host

    def _probe_host(self, h, timeout=6):
        try:
            with self._open(h + '/', timeout=timeout) as r:
                html = r.read().decode('utf-8', 'ignore')
            return any(m in html for m in _PAGE_MARKERS)
        except Exception:
            return False

    # ---------------- HTTP（urllib，含域名 failover） ----------------
    def _open(self, url, timeout=20):
        req = urllib.request.Request(url, headers={
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.host + '/',
        })
        return urllib.request.urlopen(req, timeout=timeout, context=self.ctx)

    def _raw(self, url, timeout=20):
        with self._open(url, timeout=timeout) as r:
            return r.read().decode('utf-8', 'ignore')

    def _get(self, rel, timeout=20, tries=2):
        """相对路径自动遍历域名并校验有效性；绝对 URL 直接取。"""
        if rel.startswith('http'):
            return self._raw(rel, timeout)
        hosts = [self.host] + [h for h in HOSTS if h != self.host]
        err = None
        for h in hosts:
            for _ in range(tries):
                try:
                    html = self._raw(h + rel, timeout)
                    if (html and len(html) > 1500
                            and any(m in html for m in _PAGE_MARKERS)):
                        if h != self.host:
                            self.host = h
                        return html
                except Exception as e:
                    err = e
                time.sleep(0.4)
        if err:
            raise err
        return ''

    # ---------------- 工具 ----------------
    @staticmethod
    def _unesc(s):
        if not s:
            return ''
        return (s.replace('&amp;', '&').replace('&#39;', "'").replace('&quot;', '"')
                 .replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ')
                 .replace('&#39;', "'"))

    @staticmethod
    def _clean(s):
        return re.sub(r'\s+', ' ', (s or '')).strip()

    @staticmethod
    def _txt(s):
        return re.sub(r'<[^>]+>', ' ', s or '')

    def _cards(self, html):
        """首页 / 分类页 / 搜索页 共用卡片提取器。"""
        out, seen = [], set()
        for m in re.finditer(r'<a class="myui-vodlist__thumb[^"]*"[^>]*?href="/detail/\?(\d+)\.html"',
                             html or ''):
            seg = (html or '')[m.start():m.start() + 700]
            vid = m.group(1)
            if vid in seen:
                continue
            mt = re.search(r'title="([^"]*)"', seg)
            mp = re.search(r'data-original="([^"]*)"', seg)
            mr = re.search(r'class="[^"]*pic-text[^"]*"[^>]*>(.*?)</', seg, re.S)
            name = self._unesc(mt.group(1)) if mt else ''
            if not name and mr:
                name = self._clean(self._unesc(self._txt(mr.group(1))))
            if not name:
                continue
            seen.add(vid)
            out.append({
                'vod_id': vid,
                'vod_name': self._clean(name),
                'vod_pic': self._unesc(mp.group(1)) if mp else '',
                'vod_remarks': '',
            })
        return out

    # ---------------- 首页 / 分类 ----------------
    def homeContent(self, filter):
        return {'class': [{'type_id': tid, 'type_name': name}
                          for tid, name in CATEGORIES.items()]}

    def homeVideoContent(self):
        try:
            html = self._get('/')
        except Exception:
            return {'list': []}
        return {'list': self._cards(html)}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1
        rel = ('/list/?%s.html' % tid) if pg <= 1 else ('/list/?%s-%d.html' % (tid, pg))
        try:
            html = self._get(rel)
        except Exception:
            return {'list': [], 'page': pg, 'pagecount': pg, 'limit': 0, 'total': 0}
        videos = self._cards(html)
        pagecount = self._pagecount(html, tid, pg)
        return {
            'list': videos,
            'page': pg,
            'pagecount': pagecount,
            'limit': len(videos) or 36,
            'total': len(videos) * pagecount,
        }

    def _pagecount(self, html, tid, cur):
        nums = [int(x) for x in
                re.findall(r'/list/\?%s-(\d+)\.html' % re.escape(tid), html)]
        mx = max(nums) if nums else cur
        return max(mx, cur)

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick, pg='1'):
        key = self._clean(key)
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        if not key or pg > 1:          # 站点搜索无翻页（第 2 页重复第 1 页）
            return {'list': [], 'page': pg}
        url = (self.host + '/search.php?searchword='
               + urllib.parse.quote(key, safe=''))
        try:
            html = self._raw(url)
        except Exception:
            return {'list': [], 'page': pg}
        # 站点风控：搜索需图片验证码 → 纯 py 无法处理，返回空
        if any(m in html for m in _CAPTCHA_MARKERS):
            return {'list': [], 'page': pg}
        return {'list': self._cards(html), 'page': pg}

    def searchContentPage(self, key, quick, pg='1'):
        return self.searchContent(key, quick, pg)

    # ---------------- 详情 ----------------
    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = str(vid).strip().strip('/').split('/')[-1].split('?')[-1]
        try:
            html = self._get('/detail/?%s.html' % vid)
        except Exception:
            return {'list': []}
        if not html:
            return {'list': []}
        d = self._detail(html, vid)
        return {'list': [d] if d else []}

    def _info_a(self, html, label):
        m = re.search(r'%s：</span><a[^>]*>([^<]+)</a>' % re.escape(label), html)
        if m:
            return self._clean(self._unesc(m.group(1)))
        return ''

    def _info_text(self, html, label):
        m = re.search(r'%s：</span>(.*?)</p>' % re.escape(label), html, re.S)
        if not m:
            m = re.search(r'%s：</span>(.*?)(?:<br\s*/?>|</div>)' % re.escape(label),
                          html, re.S)
        if not m:
            return ''
        return self._clean(self._unesc(self._txt(m.group(1))))

    def _detail(self, html, vid):
        name = ''
        m = re.search(r'<h1 class="title[^"]*">(.*?)</h1>', html, re.S)
        if m:
            name = self._clean(self._unesc(m.group(1)))
        mp = re.search(r'<div class="myui-content__thumb">.*?data-original="([^"]+)"',
                       html, re.S)
        pic = self._unesc(mp.group(1)) if mp else ''

        content = ''
        mc = re.search(r'<span class="sketch content">(.*?)</span>', html, re.S)
        if not mc:
            mc = re.search(r'简介：</span>(.*?)</p>', html, re.S)
        if mc:
            content = self._clean(self._unesc(self._txt(mc.group(1))))

        director = self._info_text(html, '导演')
        actor = self._info_text(html, '主演')
        area = self._info_a(html, '地区')
        year = self._info_a(html, '年份')
        type_name = self._info_a(html, '分类')

        froms, urls = self._lines(html)
        return {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': pic,
            'vod_content': content,
            'vod_actor': actor,
            'vod_director': director,
            'vod_area': area,
            'vod_year': year,
            'type_name': type_name,
            'vod_play_from': '$$$'.join(froms),
            'vod_play_url': '$$$'.join(urls),
        }

    def _lines(self, html):
        """线路名来自 nav-tabs，剧集来自各 playlist 块里的 myui-content__list。"""
        name_list = []
        for blk in re.findall(r'<ul class="nav nav-tabs[^"]*">(.*?)</ul>', html, re.S):
            name_list += [self._clean(x) for x in
                          re.findall(r'<a[^>]*>([^<]+)</a>', blk)]
        froms, urls = [], []
        for idx, part in enumerate(html.split('<div id="playlist')[1:], start=1):
            m = re.search(r'<ul class="myui-content__list[^"]*"[^>]*>(.*?)</ul>',
                          part, re.S)
            if not m:
                continue
            eps = []
            for e in re.finditer(
                    r'<a title="([^"]*)"\s+href="/video/\?(\d+)-(\d+)-(\d+)\.html"[^>]*>([^<]*)</a>',
                    m.group(1)):
                ep = self._clean(self._unesc(e.group(1) or e.group(5))) \
                    or ('第%d集' % (len(eps) + 1))
                eps.append('%s$%s|%s|%s' % (ep, e.group(2), e.group(3), e.group(4)))
            if eps:
                nm = name_list[idx - 1] if idx - 1 < len(name_list) else ('线路%d' % idx)
                froms.append(nm)
                urls.append('#'.join(eps))
        return froms, urls

    # ---------------- 播放 ----------------
    def playerContent(self, flag, id, vipFlags):
        parts = (id or '').strip().split('|')
        if len(parts) != 3:
            return {'parse': 1, 'url': self.host + '/',
                    'header': json.dumps({'User-Agent': UA, 'Referer': self.host + '/'})}
        vid, sid, nid = parts
        play_url = '%s/video/?%s-%s-%s.html' % (self.host, vid, sid, nid)
        try:
            html = self._raw(play_url)
        except Exception:
            return {'parse': 1, 'url': play_url,
                    'header': json.dumps({'User-Agent': UA, 'Referer': self.host + '/'})}
        m = re.search(r'var\s+now\s*=\s*"([^"]+)"', html)
        if not m:
            return {'parse': 1, 'url': play_url,
                    'header': json.dumps({'User-Agent': UA, 'Referer': self.host + '/'})}
        url = m.group(1).strip()
        if not url.startswith('http'):
            url = self.host.rstrip('/') + '/' + url.lstrip('/')
        return {
            'parse': 0,
            'url': url,
            'header': json.dumps({'User-Agent': UA, 'Referer': self.host + '/'}),
        }

    # ---------------- 本地代理（源站直链，无需代理） ----------------
    def localProxy(self, param):
        return None

    # ---------------- 兼容性占位 ----------------
    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv)(\?|$)', url or ''))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass


if __name__ == '__main__':
    sp = Spider()
    print('name:', sp.getName())
    print('host:', sp.init(''))
