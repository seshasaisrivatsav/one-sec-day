"""Windows desktop editor. Launch with python editor/app.py."""
from __future__ import annotations
import copy
from datetime import datetime
import os
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QSize, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QIcon, QPixmap, QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSplitter, QScrollArea, QListWidget, QListWidgetItem,
    QListView, QAbstractItemView, QFileDialog, QDialog, QDialogButtonBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QLineEdit, QMessageBox, QDoubleSpinBox, QInputDialog,
    QPlainTextEdit, QStackedWidget)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

if __package__:
    from . import core
else:
    import core

ROOT = Path(__file__).resolve().parents[1]


class Worker(QThread):
    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent); self.function=function

    def run(self):
        try:
            self.done.emit(self.function(self.progress.emit))
        except Exception:
            self.failed.emit(traceback.format_exc())


class WindowPicker(QWidget):
    """A draggable, fixed one-second selection on the source duration."""
    changed = Signal(float)

    def __init__(self):
        super().__init__(); self.duration=1.; self.start=0.; self.setMinimumHeight(54)
        self.setToolTip('Drag the blue one-second window. Fine-tune its start with the seconds field.')

    def configure(self,duration,start):
        self.duration=max(1.,float(duration)); self.start=float(start); self.update()

    def paintEvent(self,event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track=QRectF(10,12,max(1,self.width()-20),26)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#343d50')); painter.drawRoundedRect(track,5,5)
        width=track.width()/self.duration
        selected=QRectF(10+self.start*width,10,max(5,width),30)
        painter.setBrush(QColor('#50adff')); painter.drawRoundedRect(selected,3,3)
        painter.setPen(QColor('#c5d1e5'))
        painter.drawText(10,51,f'{self.start:.3f}s → {self.start+1:.3f}s     /     {self.duration:.2f}s source')

    def move_to(self,x):
        self.start=round(max(0,min(self.duration-1,(x-10)/max(1,self.width()-20)*self.duration-.5)),3)
        self.update(); self.changed.emit(self.start)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton: self.move_to(event.position().x())

    def mouseMoveEvent(self,event):
        if event.buttons() & Qt.MouseButton.LeftButton: self.move_to(event.position().x())


class Strip(QListWidget):
    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.ViewMode.IconMode); self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False); self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static); self.setIconSize(QSize(128,72))
        self.setGridSize(QSize(154,110)); self.setFixedHeight(132)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def wheelEvent(self,event):
        delta=event.pixelDelta().x() or event.pixelDelta().y() or event.angleDelta().y()
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-delta)
        event.accept()


class FoldersDialog(QDialog):
    def __init__(self,sources,parent):
        super().__init__(parent); self.setWindowTitle('Import folders'); self.resize(880,390)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Add all photo and video folders. Subfolders are included. Set each source and capture timezone.'))
        self.table=QTableWidget(0,4); self.table.setHorizontalHeaderLabels(['Folder','Source','Timezone','Video clock'])
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        for source in sources: self.add(source)
        bar=QHBoxLayout(); layout.addLayout(bar)
        add=QPushButton('Add folders…'); add.clicked.connect(self.choose); bar.addWidget(add)
        remove=QPushButton('Remove selected'); remove.clicked.connect(self.remove); bar.addWidget(remove)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def add(self,source):
        index=self.table.rowCount(); self.table.insertRow(index)
        self.table.setItem(index,0,QTableWidgetItem(source['path']))
        kind=QComboBox(); kind.addItems(['mobile','camera']); kind.setCurrentText(source['type'])
        self.table.setCellWidget(index,1,kind)
        self.table.setItem(index,2,QTableWidgetItem(source.get('timezone','America/Chicago')))
        clock=QComboBox(); clock.addItems(['utc','local']); clock.setCurrentText(source.get('video_clock','utc'))
        self.table.setCellWidget(index,3,clock)
        kind.currentTextChanged.connect(lambda value:clock.setCurrentText('utc' if value=='mobile' else 'local'))

    def choose(self):
        dialog=QFileDialog(self,'Select source folders')
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog,True)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        for view in dialog.findChildren(QAbstractItemView):
            view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        if dialog.exec():
            existing={self.table.item(i,0).text().casefold() for i in range(self.table.rowCount())}
            for folder in dialog.selectedFiles():
                if Path(folder).is_dir() and folder.casefold() not in existing:
                    self.add(dict(path=folder,type='mobile')); existing.add(folder.casefold())

    def remove(self):
        for row in sorted({i.row() for i in self.table.selectedIndexes()},reverse=True): self.table.removeRow(row)

    def sources(self):
        from zoneinfo import ZoneInfo
        result=[]
        for i in range(self.table.rowCount()):
            path=self.table.item(i,0).text().strip(); zone=self.table.item(i,2).text().strip()
            if not Path(path).is_dir(): raise ValueError('Folder unavailable: '+path)
            ZoneInfo(zone)
            result.append(dict(path=str(Path(path).resolve()),type=self.table.cellWidget(i,1).currentText(),
                               timezone=zone,video_clock=self.table.cellWidget(i,3).currentText()))
        return result


class Editor(QMainWindow):
    def __init__(self,project_path=None):
        super().__init__(); self.setWindowTitle('One Second Day • Editor'); self.resize(1440,940)
        self.project=core.fresh(); self.project_path=None; self.current=None; self.start=0
        self.timeline_context=False
        self.worker=None; self.thumbnail_worker=None; self.thumb_items={}; self.busy=False
        self.cache=ROOT/'runtime'/'editor-cache'; self.cache.mkdir(parents=True,exist_ok=True)
        self.root=QWidget(); self.setCentralWidget(self.root); layout=QVBoxLayout(self.root)
        header=QHBoxLayout(); layout.addLayout(header)
        title=QLabel('ONE SECOND DAY'); title.setStyleSheet('font-size:20px;font-weight:700;color:#7cc4ff'); header.addWidget(title)
        header.addStretch()
        self.import_button=self.button('Import folders…',self.import_folders,header)
        self.open_button=self.button('Open project',self.open_project,header)
        self.button('Save as…',self.save_as,header)
        self.month=QComboBox(); self.month.setMinimumWidth(110); self.month.currentTextChanged.connect(self.month_changed); header.addWidget(self.month)
        self.button('Add month',self.add_month,header)
        self.priority=QComboBox(); self.priority.addItems(['Mobile priority','Camera priority']); self.priority.currentIndexChanged.connect(self.priority_changed); header.addWidget(self.priority)
        self.auto_button=self.button('Auto-select month',self.auto_select,header)
        self.split=QSplitter(Qt.Orientation.Vertical); layout.addWidget(self.split,1)
        top=QSplitter(Qt.Orientation.Horizontal); self.split.addWidget(top)
        library=QWidget(); left=QVBoxLayout(library)
        self.library_title=QLabel('MEDIA  •  Videos above photos, ordered by capture time'); left.addWidget(self.library_title)
        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); left.addWidget(self.scroll)
        top.addWidget(library)
        preview=QWidget(); right=QVBoxLayout(preview); top.addWidget(preview)
        self.preview_title=QLabel('PREVIEW  •  Select media or a timeline day'); right.addWidget(self.preview_title)
        self.video=QVideoWidget(); self.video.setMinimumSize(280,180)
        self.still=QLabel(); self.still.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewer=QStackedWidget(); self.viewer.addWidget(self.video); self.viewer.addWidget(self.still); right.addWidget(self.viewer,1)
        self.player=QMediaPlayer(self); self.audio=QAudioOutput(self); self.player.setAudioOutput(self.audio); self.player.setVideoOutput(self.video)
        self.player.errorOccurred.connect(lambda *_: self.statusBar().showMessage('Playback: '+self.player.errorString()))
        self.player.mediaStatusChanged.connect(self.media_ready)
        self.pending_position=0; self.pending_play=False
        self.caption=QLabel('Import folders to begin.'); self.caption.setWordWrap(True); right.addWidget(self.caption)
        self.picker=WindowPicker(); self.picker.changed.connect(self.change_start); right.addWidget(self.picker)
        controls=QHBoxLayout(); right.addLayout(controls)
        controls.addWidget(QLabel('Start:')); self.seconds=QDoubleSpinBox(); self.seconds.setDecimals(3); self.seconds.setSingleStep(1/30); self.seconds.setSuffix(' s'); self.seconds.valueChanged.connect(self.change_start); controls.addWidget(self.seconds)
        self.button('Play / Pause',self.play_pause,controls)
        self.preview_button=self.button('Play 1 second',self.play_excerpt,controls)
        self.use_button=self.button('Use for this day',self.use_current,right)
        self.assign_button=self.button('Assign date to undated media',self.assign_date,right)
        bottom=QWidget(); bottom_layout=QVBoxLayout(bottom); self.split.addWidget(bottom)
        tools=QHBoxLayout(); bottom_layout.addLayout(tools)
        self.timeline_title=QLabel('MONTH TIMELINE'); tools.addWidget(self.timeline_title); tools.addStretch()
        self.button('Unlock selected day',self.unlock,tools)
        self.timeline_button=self.button('Play timeline from selected day',self.play_timeline,tools)
        self.resolution=QComboBox(); self.resolution.addItems(core.RESOLUTIONS); tools.addWidget(self.resolution)
        self.export_button=self.button('Export month…',self.export,tools)
        self.timeline=Strip(); self.timeline.setMinimumHeight(132); bottom_layout.addWidget(self.timeline,1)
        self.timeline.itemClicked.connect(self.timeline_clicked)
        self.button('Import / scoring issues',self.show_issues,bottom_layout)
        top.setSizes([770,590]); self.split.setSizes([650,260])
        top.setChildrenCollapsible(False); self.split.setChildrenCollapsible(False)
        self.setStyleSheet('''QWidget {background:#181e29;color:#e5eaf4;font-size:12px;}
            QPushButton,QComboBox,QDoubleSpinBox,QLineEdit {background:#293449;border:1px solid #46536a;border-radius:5px;padding:7px;}
            QPushButton:hover {background:#354965;} QPushButton:disabled {color:#69768a;}
            QListWidget,QScrollArea,QVideoWidget {background:#101620;border:1px solid #2a3547;border-radius:5px;}
            QListWidget::item:selected {background:#27668b;border:2px solid #7dcfff;}
            QSplitter::handle {background:#3c495f;} QSplitter::handle:hover {background:#64b9ff;}
            QScrollBar:horizontal {height:13px;} QLabel {padding:3px;}''')
        self.seek_timer=QTimer(self); self.seek_timer.setSingleShot(True); self.seek_timer.timeout.connect(self.seek_source)
        if project_path: self.load_project(project_path)
        else: self.refresh()

    @staticmethod
    def button(label,slot,layout):
        button=QPushButton(label); button.clicked.connect(slot); layout.addWidget(button); return button

    def error(self,text):
        QMessageBox.warning(self,'One Second Day',str(text))

    def run_job(self,function,done):
        if self.busy: return
        self.busy=True
        for widget in [self.import_button,self.open_button,self.auto_button,self.preview_button,self.timeline_button,self.export_button,self.use_button,self.assign_button,self.priority,self.month]: widget.setEnabled(False)
        worker=Worker(function,self); self.worker=worker
        worker.progress.connect(self.statusBar().showMessage)
        worker.done.connect(done); worker.failed.connect(self.error)
        worker.finished.connect(self.job_finished); worker.start()

    def job_finished(self):
        self.busy=False
        for widget in [self.import_button,self.open_button,self.auto_button,self.preview_button,self.timeline_button,self.export_button,self.use_button,self.assign_button,self.priority,self.month]: widget.setEnabled(True)
        self.statusBar().showMessage('Ready'); self.worker=None

    def persist(self):
        if self.project_path: core.save(self.project_path,self.project)

    def save_as(self):
        if self.busy: return
        path,_=QFileDialog.getSaveFileName(self,'Save editor project',str(ROOT/'runtime'/'my-month.osd.json'),'One Second Day (*.osd.json)')
        if path:
            self.project_path=Path(path); self.persist(); self.setWindowTitle('One Second Day • '+self.project_path.name)

    def open_project(self):
        if self.busy: return
        path,_=QFileDialog.getOpenFileName(self,'Open project','','One Second Day (*.json)')
        if path: self.load_project(path)

    def load_project(self,path):
        try:
            project=core.load(path); self.player.stop(); self.project=project; self.project_path=Path(path); self.current=None
            self.priority.blockSignals(True); self.priority.setCurrentIndex(int(project['priority']=='camera')); self.priority.blockSignals(False)
            self.refresh_months(); self.setWindowTitle('One Second Day • '+self.project_path.name)
        except Exception as error: self.error(error)

    def import_folders(self):
        dialog=FoldersDialog(self.project['sources'],self)
        if not dialog.exec(): return
        try: sources=dialog.sources()
        except Exception as error: self.error(error); return
        if not sources: return
        if not self.project_path:
            self.save_as()
            if not self.project_path: return
        def complete(value):
            manual={r['path']:r for r in self.project['records'] if r.get('date_source')=='manual'}
            self.project['sources']=sources; self.project['records'],self.project['issues']=value
            for record in self.project['records']:
                if record['path'] in manual:
                    prior=manual[record['path']]
                    record.update({key:prior[key] for key in ['day','capture_local','date_source']})
            allowed={r['path'] for r in self.project['records']}
            self.project['selections']={d:r for d,r in self.project['selections'].items() if r['kind']=='missing' or r['path'] in allowed}
            self.project['locked']=[d for d in self.project['locked'] if d in self.project['selections']]
            self.refresh_months(); self.persist()
            QTimer.singleShot(100,self.auto_select)
        self.run_job(lambda progress:core.scan(sources,self.cache,progress),complete)

    def refresh_months(self):
        available=core.months(self.project)
        self.month.blockSignals(True); self.month.clear(); self.month.addItems(available)
        if self.project['month'] in available: self.month.setCurrentText(self.project['month'])
        elif available: self.project['month']=available[0]
        self.month.blockSignals(False); self.refresh()

    def add_month(self):
        if self.busy:return
        month,ok=QInputDialog.getText(self,'Month','YYYY-MM:',text=datetime.now().strftime('%Y-%m'))
        if ok:
            try:
                if datetime.strptime(month,'%Y-%m').strftime('%Y-%m')!=month: raise ValueError('Use YYYY-MM')
                self.project['month']=month; self.refresh_months(); self.persist()
            except ValueError as error:self.error(error)

    def month_changed(self,month):
        if not month:return
        self.player.stop(); self.project['month']=month; self.current=None; self.refresh(); self.persist()

    def priority_changed(self,index):
        self.project['priority']='camera' if index else 'mobile'; self.persist()
        self.statusBar().showMessage('Priority changed. Click Auto-select month to update unlocked days.')

    def auto_select(self):
        month=self.project['month']
        if not month or self.busy:return
        snapshot=copy.deepcopy(self.project)
        def complete(project): self.project=project; self.persist(); self.refresh()
        self.run_job(lambda progress:core.automatic(snapshot,month,self.cache,progress),complete)

    def refresh(self):
        self.thumb_items={}; content=QWidget(); layout=QVBoxLayout(content)
        month=self.project['month']; days=core.reel.month_days(month) if month else []
        for day in days+['']:
            records=[r for r in self.project['records'] if r['day']==day]
            layout.addWidget(QLabel((day or 'Uncategorised')+f'  •  {len(records)} media'))
            for kind in ['video','photo']:
                media=sorted((r for r in records if r['kind']==kind),key=lambda r:(r['capture_local'],r['path']))
                if not media:
                    label=QLabel('   No '+('videos' if kind=='video' else 'photos')); label.setStyleSheet('color:#78879e'); layout.addWidget(label); continue
                strip=Strip(); layout.addWidget(strip)
                for rec in media:
                    chosen=self.project['selections'].get(day,{}).get('path')==rec['path']
                    stamp=rec['capture_local'][11:19] or Path(rec['path']).name
                    item=QListWidgetItem(('Selected · ' if chosen else '')+stamp+'\n'+rec['source']+' · '+kind)
                    item.setData(Qt.ItemDataRole.UserRole,rec); item.setToolTip(rec['path']+'\n'+rec.get('warnings',''))
                    if chosen:item.setBackground(QColor('#174e48'))
                    strip.addItem(item); self.thumb_items.setdefault(rec['path'],[]).append(item)
                strip.itemClicked.connect(lambda item:self.show_record(item.data(Qt.ItemDataRole.UserRole)))
        layout.addStretch(); self.scroll.setWidget(content)
        self.timeline.clear()
        for index,row in enumerate(core.rows(self.project,month) if month else []):
            label=f'{index:02d}s  ·  {row["day"][-2:]}\n'+row['kind']+(' · manual' if row['day'] in self.project['locked'] else '')
            item=QListWidgetItem(label); item.setData(Qt.ItemDataRole.UserRole,row); self.timeline.addItem(item)
            if row['path']:self.thumb_items.setdefault(row['path'],[]).append(item)
        self.timeline_title.setText(f'{month or "MONTH"} TIMELINE  •  {len(days)} seconds')
        self.load_thumbnails()

    def load_thumbnails(self):
        if self.thumbnail_worker and self.thumbnail_worker.isRunning():
            self.thumbnail_worker.finished.connect(self.load_thumbnails,Qt.ConnectionType.SingleShotConnection); return
        records=[r for r in self.project['records'] if r['path'] in self.thumb_items]
        def work(progress):
            for rec in records:
                try: progress(rec['path']+'\t'+core.thumbnail(rec,self.cache))
                except Exception: pass
        worker=Worker(work,self); self.thumbnail_worker=worker
        def apply(value):
            path,thumb=value.split('\t',1)
            for item in self.thumb_items.get(path,[]): item.setIcon(QIcon(thumb))
        worker.progress.connect(apply); worker.start()

    def show_record(self,record,start=None):
        if self.busy:return
        self.timeline_context=False
        self.player.stop(); self.current=record
        self.start=core.reel.default_start(record) if start is None else float(start)
        duration=record.get('duration',0)
        self.seconds.blockSignals(True); self.seconds.setRange(0,max(0,duration-1)); self.seconds.setValue(self.start); self.seconds.blockSignals(False)
        self.picker.configure(duration,self.start)
        self.picker.setEnabled(record['kind']=='video'); self.seconds.setEnabled(record['kind']=='video')
        self.caption.setText(record.get('capture_local') or record['day'] or 'Undated media — assign a date to use it')
        self.preview_title.setText('PREVIEW  •  '+(Path(record['path']).name if record.get('path') else 'Missing-day card'))
        if record['kind']=='video': self.play_file(record['path'],int(self.start*1000),False)
        elif record['day']: self.play_excerpt()
        else:
            # Undated photos can still be inspected without inventing a capture date.
            try:
                from PIL.ImageQt import ImageQt
                with core.reel.open_photo(record['path']) as photo:
                    photo.thumbnail((960,540)); pixmap=QPixmap.fromImage(ImageQt(photo))
                self.still.setPixmap(pixmap.scaled(self.viewer.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
                self.viewer.setCurrentWidget(self.still)
            except Exception as error:self.error(error)

    def timeline_clicked(self,item):
        if self.busy:return
        row=item.data(Qt.ItemDataRole.UserRole)
        rec=next((r for r in self.project['records'] if r['path']==row['path']),row)
        self.show_record(rec,float(row['start_seconds'] or 0))
        self.timeline_context=True

    def change_start(self,value):
        self.start=float(value); self.picker.configure(self.picker.duration,value)
        self.seconds.blockSignals(True); self.seconds.setValue(value); self.seconds.blockSignals(False)
        self.seek_timer.start(150)

    def seek_source(self):
        if self.current and self.current['kind']=='video':self.play_file(self.current['path'],int(self.start*1000),False)

    def play_file(self,path,position=0,play=True):
        self.viewer.setCurrentWidget(self.video)
        self.pending_position=position; self.pending_play=play
        url=QUrl.fromLocalFile(str(Path(path).resolve()))
        if self.player.source()==url:
            self.player.setPosition(position)
            if play:self.player.play()
            else:self.player.pause()
        else:self.player.setSource(url)

    def media_ready(self,status):
        if status==QMediaPlayer.MediaStatus.LoadedMedia:
            self.player.setPosition(self.pending_position)
            if self.pending_play:self.player.play()

    def play_pause(self):
        if self.timeline_context:
            self.play_timeline();return
        if self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState:self.player.pause()
        else:self.player.play()

    def play_excerpt(self):
        if not self.current or self.busy:return
        if not self.current['day']:self.error('Assign a capture date first.');return
        rec=copy.deepcopy(self.current); start=self.start
        if rec['kind']=='video' and rec['duration']<=1:self.error('This video is too short. Choose a photo or longer video.');return
        self.run_job(lambda progress:core.preview(rec,start,self.project,self.cache),lambda path:self.play_file(path))

    def use_current(self):
        if not self.current or self.busy:return
        try:core.select(self.project,self.current,self.start); self.persist(); self.refresh()
        except Exception as error:self.error(error)

    def assign_date(self):
        if not self.current or self.current['day'] or self.busy:return
        value,ok=QInputDialog.getText(self,'Assign capture date','YYYY-MM-DD or YYYY-MM-DD HH:MM:SS:')
        if ok:
            try:
                parsed=datetime.fromisoformat(value)
                self.current.update(day=parsed.date().isoformat(),capture_local=value.replace(' ','T'),date_source='manual')
                self.persist(); self.refresh_months()
            except ValueError:self.error('Enter a valid date or timestamp.')

    def unlock(self):
        if self.busy:return
        item=self.timeline.currentItem()
        if item:
            day=item.data(Qt.ItemDataRole.UserRole)['day']
            self.project['locked']=[d for d in self.project['locked'] if d!=day]; self.persist(); self.refresh()

    def play_timeline(self):
        if not self.project['month'] or self.busy:return
        self.timeline_context=False
        index=max(0,self.timeline.currentRow()); project=copy.deepcopy(self.project); month=project['month']
        out=self.cache/'timeline'/str(abs(hash(str(self.project_path))))/month
        self.run_job(lambda progress:core.render_month(project,month,out,(960,540)),lambda path:self.play_file(path,index*1000))

    def export(self):
        if not self.project['month'] or self.busy:return
        folder=QFileDialog.getExistingDirectory(self,'Choose export folder',str(ROOT.parent/'one-sec-day-output'/'editor'))
        if not folder:return
        project=copy.deepcopy(self.project); month=project['month']; size=core.RESOLUTIONS[self.resolution.currentText()]
        out=Path(folder)/self.resolution.currentText().split()[0]
        self.run_job(lambda progress:core.render_month(project,month,out,size),lambda path:QMessageBox.information(self,'Export complete',path))

    def show_issues(self):
        dialog=QDialog(self); dialog.setWindowTitle('Import and scoring issues'); dialog.resize(800,450)
        layout=QVBoxLayout(dialog); text=QPlainTextEdit(); text.setReadOnly(True)
        text.setPlainText('\n\n'.join(r['path']+'\n'+r['reason'] for r in self.project['issues']) or 'No issues recorded.')
        layout.addWidget(text); dialog.exec()

    def closeEvent(self,event):
        if self.busy or (self.thumbnail_worker and self.thumbnail_worker.isRunning()):
            self.statusBar().showMessage('Please wait for the current import, thumbnails, preview, or export to finish.');event.ignore();return
        self.persist(); self.player.stop(); event.accept()


def main():
    app=QApplication(sys.argv); app.setStyle('Fusion')
    font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeui.ttf'
    if font.exists():QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Segoe UI',10))
    window=Editor(sys.argv[1] if len(sys.argv)>1 else None); window.show()
    sys.exit(app.exec())


if __name__=='__main__':main()
