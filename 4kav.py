# coding=utf-8
# !/usr/bin/python
# 4K-AV (4k-av.com) TVBox 源 —— 按电影猎手格式编写
# 站点结构: 分类 /movie/ /tv/ /年份/; 分页 /page-N.html
# 详情页内嵌 <source src="...m3u8"> 直链; 剧集每集独立页面, 选集在 rtlist 中
# by WorkBuddy 2026-09-24
import sys
import os
sys.path.append("..")
import re
import json
import time
import html as htmllib
from base.spider import Spider


class Spider(Spider):

    host = "https://4k-av.com"
    _ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
           '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    _cache = {}
    _cache_time = {}

    def getName(self):
        return "4K-AV"

    def init(self, extend=""):
        self.host = "https://4k-av.com"
        self._ua = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        self._cache = {}
        self._cache_time = {}

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ---------------- 基础工具 ----------------

    def header(self):
        return {
            'User-Agent': self._ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def _clean(self, s):
        try:
            s = re.sub(r'<[^>]+>', '', s or '')
            return htmllib.unescape(s).strip()
        except Exception:
            return (s or '').strip()

    def _get(self, url):
        try:
            r = self.fetch(url, headers=self.header(), timeout=12)
        except TypeError:
            # 运行时不支持 timeout 参数
            r = self.fetch(url, headers=self.header())
        if isinstance(r, str):
            return r
        if hasattr(r, 'status_code') and int(r.status_code) != 200:
            raise Exception('http %s' % r.status_code)
        return r.text

    def _cache_get(self, key, ttl):
        try:
            t = self._cache_time.get(key, 0)
            if t and (time.time() - t) < ttl and key in self._cache:
                return self._cache[key]
        except Exception:
            pass
        return None

    def _cache_set(self, key, val):
        try:
            if len(self._cache) > 64:
                self._cache.clear()
                self._cache_time.clear()
            self._cache[key] = val
            self._cache_time[key] = time.time()
        except Exception:
            pass

    # ---------------- 列表解析 ----------------

    def parse_list(self, html):
        videos = []
        try:
            blocks = re.split(r'<div class="(?:NT|RT)Mitem">', html)[1:]
            for b in blocks:
                tm = re.search(r'<div class="title"><a[^>]*href="(/(?:en/)?(?:movie|tv)/[^"]+)"[^>]*>', b)
                if not tm:
                    continue
                path = tm.group(1).strip('/')
                # 规范化: 去掉英文版 /en/ 前缀(剧集条目链接固定带 en/, 不处理会导致分类/详情/选集全空)
                if path.startswith('en/'):
                    path = path[3:]
                name = ''
                nm = re.search(r'<div class="title"><a[^>]*title="([^"]*)"', b)
                if nm:
                    name = self._clean(nm.group(1))
                if not name:
                    hm = re.search(r'<div class="title"><a[^>]*><h2>(.*?)</h2>', b, re.S)
                    if hm:
                        name = self._clean(hm.group(1))
                if not name:
                    continue
                pic = ''
                pm = re.search(r'<div class="poster"><a[^>]*>\s*<img src="([^"]+)"', b)
                if not pm:
                    pm = re.search(r'<div class="poster"><a[^>]*><div><img src="([^"]+)"', b)
                if pm:
                    pic = pm.group(1)
                remarks = ''
                rm = re.search(r'<label title="分辨率"[^>]*>([^<]*)</label>\s*<label title="年份">([^<]*)</label>', b)
                if rm:
                    remarks = '%s · %s' % (self._clean(rm.group(1)), self._clean(rm.group(2)))
                else:
                    sm = re.search(r'<span>(4K[^<]*|1080P[^<]*|720P[^<]*)</span>', b)
                    if sm:
                        remarks = self._clean(sm.group(1))
                videos.append({
                    'vod_id': path,
                    'vod_name': name,
                    'vod_pic': pic,
                    'vod_remarks': remarks,
                })
        except Exception:
            pass
        return videos

    def _pagecount(self, html):
        try:
            m = re.search(r'页次\s*\d+/(\d+)', html)
            if m:
                return int(m.group(1))
            m = re.search(r'Page\s+\d+\s*/\s*(\d+)', html)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return 9999

    # ---------------- TVBox 接口 ----------------

    def homeContent(self, filter):
        result = {}
        try:
            classes = [
                {'type_name': '电影', 'type_id': 'movie'},
                {'type_name': '剧集', 'type_id': 'tv'},
            ]
            years = ['2026', '2025', '2024', '2023', '2022', '2021', '2020', '2019']
            filters = {}
            for tid in ('movie', 'tv'):
                filters[tid] = [{
                    'key': 'year', 'name': '年份',
                    'value': [{'n': y + '年', 'v': y} for y in years],
                }]
            result['class'] = classes
            result['filters'] = filters
        except Exception:
            pass
        return result

    def homeVideoContent(self):
        result = {'list': []}
        try:
            cached = self._cache_get('home', 600)
            if cached is not None:
                return cached
            html = self._get(self.host + '/')
            result['list'] = self.parse_list(html)
            self._cache_set('home', result)
        except Exception:
            pass
        return result

    def categoryContent(self, tid, pg, filter, extend):
        result = {}
        try:
            tid = str(tid or 'movie')
            if tid not in ('movie', 'tv'):
                tid = 'movie'
            try:
                p = int(pg)
            except Exception:
                p = 1
            if p < 1:
                p = 1
            year = ''
            try:
                year = str((extend or {}).get('year', '')).strip()
            except Exception:
                year = ''
            if re.match(r'^\d{4}$', year):
                base = '/' + year
            else:
                base = '/' + tid
            url = self.host + base + '/' if p <= 1 else '%s%s/page-%d.html' % (self.host, base, p)
            key = 'cat:%s:%d' % (base, p)
            cached = self._cache_get(key, 300)
            if cached is not None:
                return cached
            html = self._get(url)
            result['list'] = self.parse_list(html)
            result['page'] = p
            result['pagecount'] = self._pagecount(html)
            result['limit'] = 24
            result['total'] = 999999
            if result['list']:
                self._cache_set(key, result)
        except Exception:
            result['list'] = []
            result['page'] = 1
            result['pagecount'] = 1
            result['limit'] = 24
            result['total'] = 0
        return result

    def detailContent(self, ids):
        result = {'list': []}
        try:
            path = str(ids[0]).strip('/')
            cached = self._cache_get('detail:' + path, 900)
            if cached is not None:
                return cached
            html = self._get(self.host + '/' + path + '/')
            video = {}
            tm = re.search(r'<div class="MainTitle"[^>]*title="([^"]*)"[^>]*>', html)
            name = self._clean(tm.group(1)) if tm else ''
            if not name:
                tm = re.search(r'<h1[^>]*title="([^"]*)"', html)
                name = self._clean(tm.group(1)) if tm else path
            video['vod_id'] = path
            video['vod_name'] = name
            # 别名/译名
            am = re.search(r'</div><h2 title="([^"]*)"', html)
            aka = self._clean(am.group(1)) if am else ''
            pm = re.search(r'id="MainContent_poster"[^>]*>\s*<a[^>]*>\s*<img src="([^"]+)"', html)
            if not pm:
                pm = re.search(r'id="MainContent_poster"[^>]*>.*?src="([^"]+)"', html, re.S)
            video['vod_pic'] = pm.group(1) if pm else ''
            ym = re.search(r'href="/(?:en/)?(\d{4})/"\s*>\s*\1\s*</a>', html)
            video['vod_year'] = ym.group(1) if ym else ''
            rm = re.search(r'(?:Resolution|分辨率)[:：]\s*([^<]*)</span>', html)
            video['vod_remarks'] = self._clean(rm.group(1)) if rm else ''
            dm = re.search(r'class="videodesc[^"]*">\s*<p[^>]*>(.*?)</p>', html, re.S)
            desc = self._clean(dm.group(1)) if dm else ''
            if aka:
                desc = '别名: ' + aka + '\n' + desc
            video['vod_content'] = desc
            # 标签
            tags = [self._clean(t) for t in re.findall(r'<div id="MainContent_tags"[^>]*>(.*?)</div>', html, re.S)]
            if tags:
                video['vod_tag'] = ' '.join(tags[:1])
            # 播放地址
            play_urls = []
            names = []
            sm = re.search(r'<source src="([^"]+)"\s+type="application/x-mpegURL"', html)
            if sm and path.startswith('movie/'):
                names.append('4K专区')
                play_urls.append('正片$' + sm.group(1))
            eps = []
            for em in re.finditer(
                    r'<a href="(/(?:en/)?tv/[^"]+)"\s+title="([^"]*)">\s*<div>\s*<img src="[^"]*screenshot[^"]*".*?<span>([^<]*)</span>',
                    html, re.S):
                ep_path = em.group(1).strip('/')
                if ep_path.startswith('en/'):
                    ep_path = ep_path[3:]
                ep_title = self._clean(em.group(2))
                ep_no = self._clean(em.group(3))
                eps.append((ep_path, ep_title, ep_no))
            if path.startswith('tv/'):
                if path not in [e[0] for e in eps]:
                    eps.insert(0, (path, name, '当前'))
                if eps:
                    names.append('选集')
                    play_urls.append('#'.join(
                        ('%s$https://4k-av.com/%s' % (e[2] if e[2] else e[1], e[0]))
                        for e in eps))
            video['vod_play_from'] = '$$$'.join(names)
            video['vod_play_url'] = '$$$'.join(play_urls)
            result['list'] = [video]
            self._cache_set('detail:' + path, result)
        except Exception:
            result['list'] = []
        return result

    def searchContent(self, key, quick, pg="1"):
        result = {'list': [], 'page': 1}
        try:
            from urllib.parse import quote
            kw = quote(str(key))
            ckey = 's:%s' % kw
            cached = self._cache_get(ckey, 300)
            if cached is not None:
                return cached
            html = ''
            try:
                html = self._get(self.host + '/s?y=' + kw)
            except Exception:
                try:
                    html = self._get(self.host + '/en/s?y=' + kw)
                except Exception:
                    html = ''
            if html:
                result['list'] = self.parse_list(html)
            result['page'] = 1
            if result['list']:
                self._cache_set(ckey, result)
        except Exception:
            result['list'] = []
        return result

    def playerContent(self, flag, id, vipFlags):
        result = {}
        url = str(id)
        try:
            result['parse'] = 0
            result['url'] = url
            result['header'] = {
                'User-Agent': self._ua,
                'Referer': self.host + '/',
            }
        except Exception:
            result['parse'] = 1
            result['url'] = url
        return result

    def localProxy(self, param):
        return [200, 'text/plain', '']
