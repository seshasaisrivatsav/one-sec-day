"""Synthetic end-to-end verification; writes only under runtime/editor-smoke."""
from pathlib import Path
import sys
import os
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editor import core
from PIL import Image,ImageDraw


def main():
    root=Path(__file__).resolve().parents[1]
    work=root/'runtime'/'editor-smoke';work.mkdir(parents=True,exist_ok=True)
    source=work/'media';source.mkdir(exist_ok=True)
    image=Image.new('RGB',(960,540),'#194b66');draw=ImageDraw.Draw(image)
    draw.rectangle((200,70,750,450),fill='#e2ad60');draw.text((320,260),'PHOTO TEST',fill='black')
    image.save(source/'2020-02-02-12-34-56.jpg');image.save(source/'undated.jpg')
    video=source/'2020-02-01-12-00-00.mp4'
    if not video.exists():
        core.reel.run([core.reel.tool('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=30',
                       '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','4','-c:v','libx264',
                       '-threads','2','-pix_fmt','yuv420p','-c:a','aac','-y',str(video)],timeout=90)
    project=core.fresh();project['sources']=[dict(path=str(source),type='mobile',timezone='America/Chicago',video_clock='utc')]
    project['records'],project['issues']=core.scan(project['sources'],work/'cache')
    project['month']='2020-02';project=core.automatic(project,'2020-02',work/'cache')
    assert len(project['records'])==3
    assert project['selections']['2020-02-01']['kind']=='video'
    assert project['selections']['2020-02-02']['kind']=='photo'
    assert project['selections']['2020-02-03']['kind']=='missing'
    for kind in ['video','photo','missing']:
        row=next(r for r in core.rows(project,'2020-02') if r['kind']==kind)
        record=next((r for r in project['records'] if r['path']==row['path']),row)
        path=core.preview(record,float(row['start_seconds']),project,work/'cache')
        core.reel.check_video(path,30)
    movie=core.render_month(project,'2020-02',work/'export',(1920,1080))
    core.reel.check_video(movie,29*30)
    for name,size in core.RESOLUTIONS.items():
        cfg=core.config(project,'2020-02',work,size)
        target=work/(name.split()[0]+'.mkv')
        core.reel.render_still(project['selections']['2020-02-02'],cfg,target)
        stream=core.reel.video_stream(core.reel.probe(target))
        assert (stream['width'],stream['height'])==size
        core.reel.check_video(target,30)
    project_path=work/'demo.osd.json';core.save(project_path,project)
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontDatabase,QFont
    from editor.app import Editor
    app=QApplication([]);QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf');app.setFont(QFont('Segoe UI',10))
    window=Editor(project_path);window.show()
    def finish():
        if window.thumbnail_worker and window.thumbnail_worker.isRunning():QTimer.singleShot(250,finish);return
        window.grab().save(str(work/'editor-populated.png'));window.close();app.quit()
    QTimer.singleShot(2000,finish);app.exec()
    print('PASS: scan, quality selection, undated retention, 3 preview types, 29-second 1080p month, all export resolutions, desktop UI')


if __name__=='__main__':main()
