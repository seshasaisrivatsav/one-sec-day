import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw
import daily_reel as r


class Rules(unittest.TestCase):
    def test_calendar(self):
        self.assertEqual(len(r.month_days('2024-02')), 29)
        self.assertEqual(len(r.month_days('2023-02')), 28)
        self.assertEqual(len(r.month_days('2023-01')), 31)
        self.assertEqual(list(r.months_between('2023-12', '2024-02')), ['2023-12', '2024-01', '2024-02'])

    def test_dates(self):
        self.assertEqual(r.parse_time('2024:02:03 04:05:06').isoformat(), '2024-02-03T04:05:06')
        self.assertIsNone(r.parse_time('0000:00:00 00:00:00'))
        self.assertEqual(r.filename_date('IMG_20240203_040506.jpg')[0], '2024-02-03T04:05:06')
        self.assertEqual(r.filename_date('2024-02-03.jpg')[0], '2024-02-03')
        self.assertEqual(r.filename_date('IMG_0001.jpg')[0], '')

    def test_priority(self):
        records = [dict(source=s, kind=k, capture_local='2024-02-01T12:00:00', path=s+k)
                   for s in ['camera', 'mobile'] for k in ['photo', 'video']]
        ordered = sorted(records, key=lambda a:r.rank(a, {'priority':'video-first'}))
        self.assertEqual([(x['source'], x['kind']) for x in ordered],
                         [('mobile','video'),('camera','video'),('mobile','photo'),('camera','photo')])
        ordered = sorted(records, key=lambda a:r.rank(a, {'priority':'mobile-first'}))
        self.assertEqual((ordered[1]['source'], ordered[1]['kind']), ('mobile', 'photo'))

    def test_timezones(self):
        source = {'video_clock':'utc', 'timezone':'America/Chicago'}
        info = {'format':{'tags':{'creation_time':'2024-02-02T02:00:00Z'}}}
        self.assertEqual(r.video_date(info, source, 'clip.mp4')[0], '2024-02-01T20:00:00-06:00')
        info['format']['tags']['com.apple.quicktime.creationdate'] = '2024-02-02T10:00:00+05:30'
        self.assertEqual(r.video_date(info, source, 'clip.mp4')[0], '2024-02-02T10:00:00+05:30')
        del info['format']['tags']['com.apple.quicktime.creationdate']
        source['video_clock'] = 'local'
        self.assertEqual(r.video_date(info, source, 'clip.mp4')[0], '2024-02-02T02:00:00')

    def test_midnight_and_timestamp(self):
        rec = dict(kind='video',duration=60,capture_local='2024-02-01T23:59:58')
        self.assertEqual(r.default_start(rec), 1)
        row = dict(kind='video', capture_local='2024-02-01T12:00:00', start_seconds=3.5)
        self.assertIn('12:00:03 PM', r.timestamp_text(row))
        row['capture_local'] = '2024-02-01'
        self.assertIn('Time unknown', r.timestamp_text(row))

    def test_exif(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work)/'arbitrary.jpg'
            image = Image.new('RGB',(32,32),'red')
            exif = Image.Exif()
            exif[36867]='2024:02:01 08:15:12'
            image.save(path, exif=exif)
            self.assertEqual(r.photo_date(path)[0], '2024-02-01T08:15:12')


class Rendering(unittest.TestCase):
    def test_full_month(self):
        with tempfile.TemporaryDirectory(prefix='reel-test-') as work:
            root=Path(work)
            mobile=root/'mobile'; mobile.mkdir()
            camera=root/'camera'; camera.mkdir()
            out=root/'out'
            im=Image.new('RGB',(180,320),'#206a8a')
            d=ImageDraw.Draw(im)
            d.rectangle((12,12,168,308), outline='yellow',width=6)
            d.ellipse((40,100,140,200), fill='orange')
            im.save(mobile/'2024-02-01_100000.jpg')
            im.save(camera/'2024-02-03_100000.jpg')
            im.save(camera/'2024-02-04_100000.jpg')
            for folder, name, dur, audio in [(mobile,'2024-02-02_100000.mp4',3,True),
                                            (camera,'2024-02-04_100000.mp4',0.3,False)]:
                args=[r.tool('ffmpeg'),'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=180x320:rate=30']
                if audio:
                    args+=['-f','lavfi','-i','sine=frequency=400:sample_rate=48000']
                args+=['-t',str(dur),'-c:v','libx264','-pix_fmt','yuv420p','-threads','1',str(folder/name)]
                r.run(args)
            cfg={'sources':[{'type':'mobile','path':str(mobile)},{'type':'camera','path':str(camera)}],
                 'output':str(out),'start_month':'2024-02','end_month':'2024-02','width':320,'height':180}
            r.write_json(root/'config.json',cfg)
            cfg=r.load_config(root/'config.json')
            records=r.scan(cfg)
            self.assertEqual(len(records),5)
            rows=r.make_plan(cfg,records)
            self.assertEqual(len(rows),29)
            self.assertEqual([x['kind'] for x in rows[:5]],['photo','video','photo','photo','missing'])
            r.render(cfg,'2024-02')
            final=out/'2024'/'2024-02.mp4'
            r.check_video(final,870)
            info=r.probe(final)
            self.assertEqual(r.video_stream(info)['width'],320)
            self.assertTrue(any(x['codec_type']=='audio' for x in info['streams']))
            signature=final.stat().st_mtime_ns
            r.render(cfg,'2024-02')
            self.assertEqual(final.stat().st_mtime_ns,signature)


if __name__=='__main__':
    unittest.main(verbosity=2)
