from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QFileDialog, QLineEdit

class FileSelectorUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Anki-slicer")
        self.setGeometry(100, 100, 600, 300)

        layout = QVBoxLayout()

        # MP3
        self.mp3_label = QLabel("Select MP3 File:")
        self.mp3_path = QLineEdit()
        self.mp3_button = QPushButton("Browse MP3")
        self.mp3_button.clicked.connect(self.select_mp3)

        layout.addWidget(self.mp3_label)
        layout.addWidget(self.mp3_path)
        layout.addWidget(self.mp3_button)

        # Original SRT
        self.orig_label = QLabel("Select Original SRT File:")
        self.orig_path = QLineEdit()
        self.orig_button = QPushButton("Browse SRT")
        self.orig_button.clicked.connect(self.select_orig_srt)

        layout.addWidget(self.orig_label)
        layout.addWidget(self.orig_path)
        layout.addWidget(self.orig_button)

        # Translation SRT
        self.trans_label = QLabel("Select Translation SRT File:")
        self.trans_path = QLineEdit()
        self.trans_button = QPushButton("Browse SRT")
        self.trans_button.clicked.connect(self.select_trans_srt)

        layout.addWidget(self.trans_label)
        layout.addWidget(self.trans_path)
        layout.addWidget(self.trans_button)

        # Set layout
        self.setLayout(layout)

    def select_mp3(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select MP3", "", "Audio Files (*.mp3)")
        if file:
            self.mp3_path.setText(file)

    def select_orig_srt(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Original SRT", "", "SubRip Files (*.srt)")
        if file:
            self.orig_path.setText(file)

    def select_trans_srt(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Translation SRT", "", "SubRip Files (*.srt)")
        if file:
            self.trans_path.setText(file)
