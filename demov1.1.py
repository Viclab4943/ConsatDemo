from PySide6.QtWidgets import QApplication, QFrame
from PySide6.QtCore import QObject, Signal, Qt, QTimer
from flask import Flask, request, jsonify
import vlc
import sys
import os
import time
import threading

app = Flask(__name__)

# Global variables
DEFAULT = os.listdir("videos/default")
VIDEOS = os.listdir("videos")
MAIN_PATH = os.path.abspath("videos")
DEFAULT_VIDEO = f"{MAIN_PATH}/default/{DEFAULT[0]}"
current_player = None

# Create a signals class for cross-thread communication
class PlayerSignals(QObject):
    change_video_signal = Signal(str)
    pause_signal = Signal()
    play_signal = Signal()
    stop_signal = Signal()
    close_signal = Signal()


class VideoPlayer:
    def __init__(self, video_path):
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Create instance without the repeat flag
        self.instance = vlc.Instance(["--no-video-title-show"])
        self.default_video = video_path
        self.video_path = video_path
        self.mediaplayer = self.instance.media_player_new()
        self.app = None
        self.video_frame = None
        self.is_running = False
        self.is_default_video = True  # Flag to track if we're playing the default video
        self.event_manager = None

        # Create signals for thread-safe operations
        self.signals = PlayerSignals()

    def setup_signals(self):
        """Connect signals to slots (call this after QApplication is created)"""
        self.signals.change_video_signal.connect(self.change_video_in_main_thread, Qt.QueuedConnection)
        self.signals.pause_signal.connect(self.pause_in_main_thread, Qt.QueuedConnection)
        self.signals.play_signal.connect(self.play_in_main_thread, Qt.QueuedConnection)
        self.signals.stop_signal.connect(self.stop_in_main_thread, Qt.QueuedConnection)
        self.signals.close_signal.connect(self.close_in_main_thread, Qt.QueuedConnection)

        self.setup_event_manager()

        # Add a polling timer as a backup for event detection
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.check_playback_status)
        self.poll_timer.start(500)  # Check every second

    def setup_event_manager(self):
        """Set up the event manager - separate method so we can call it again later"""
        print("Setting up event manager")
        self.event_manager = self.mediaplayer.event_manager()
        self.event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self.on_media_end)

    def on_media_end(self, event):
        """Handler for when media playback ends"""
        print("Media playback ended event triggered")
        # Use a timer to delay execution slightly
        QTimer.singleShot(100, self.handle_media_end)

    def handle_media_end(self):
        """This method handles what happens when media ends (called via QTimer)"""
        print("Handling media end")

        # If we just finished playing a non-default video, go back to the default
        if not self.is_default_video:
            print("Non-default video finished, returning to default video")
            self.is_default_video = True
            self.change_video_in_main_thread(self.default_video)
        else:
            # We're already playing the default video, just loop it
            print("Default video finished, looping default video")
            self.play_in_main_thread()

    def check_playback_status(self):
        """Poll method to check playback state"""
        state = self.mediaplayer.get_state()

        # Only check for Ended state to avoid console flooding
        if state == vlc.State.Ended:
            print("Polling detected end of media")
            self.handle_media_end()

    def change_video_in_main_thread(self, new_path):
        """This method runs in the main thread"""
        print(f"Changing video to {new_path} in main thread")
        if os.path.exists(new_path):
            self.video_path = new_path

            # Set flag based on whether this is the default video
            self.is_default_video = (new_path == self.default_video)
            print(f"Is default video: {self.is_default_video}")

            # Stop current playback if any
            if self.mediaplayer.is_playing():
                self.mediaplayer.stop()

            # Play the new video
            self.play_in_main_thread()
            return True
        else:
            print(f"File not found: {new_path}")
            return False

    def change_video(self, new_path):
        """This method can be called from any thread"""
        print(f"Requesting video change to {new_path}")
        # Emit signal to change video in main thread
        self.signals.change_video_signal.emit(new_path)
        return True

    def play_in_main_thread(self):
        """Play method that runs in the main thread"""
        try:
            # Create a new media object
            media = self.instance.media_new(self.video_path)

            # Set the media to the player
            self.mediaplayer.set_media(media)

            # Re-attach the event manager for this new media
            self.setup_event_manager()

            # Start playback
            self.mediaplayer.play()

            # Update window title
            if self.video_frame:
                title_prefix = "[DEFAULT] " if self.is_default_video else ""
                self.video_frame.setWindowTitle(f"{title_prefix}Video Player - {os.path.basename(self.video_path)}")

            return True
        except Exception as e:
            print(f"Error playing video: {e}")
            return False

    def play(self):
        """This can be called from any thread"""
        self.signals.play_signal.emit()
        return True

    def pause_in_main_thread(self):
        """Pause method that runs in the main thread"""
        if self.mediaplayer.is_playing():
            self.mediaplayer.pause()
            return True
        else:
            self.mediaplayer.play()
        return False

    def pause(self):
        """This can be called from any thread"""
        self.signals.pause_signal.emit()
        return True

    def stop_in_main_thread(self):
        """Stop method that runs in the main thread"""
        if self.mediaplayer.is_playing():
            self.mediaplayer.stop()
            return True
        return False

    def stop(self):
        """This can be called from any thread"""
        self.signals.stop_signal.emit()
        return True

    def close_in_main_thread(self):
        """Close method that runs in the main thread"""
        try:
            # Stop playback if it's playing
            if self.mediaplayer.is_playing():
                self.mediaplayer.stop()

            # Check if window exists
            if self.video_frame:
                self.video_frame.close()

            # Check if app exists and is running
            if self.app and self.is_running:
                self.app.quit()

            return True
        except Exception as e:
            print(f"Error closing video player: {e}")
            import traceback
            traceback.print_exc()
            return False

    def close(self):
        """This can be called from any thread"""
        self.signals.close_signal.emit()
        return True

    def vlcApp(self):
        self.app = QApplication([])
        self.is_running = True

        # Set up signal connections after QApplication is created
        self.setup_signals()

        self.video_frame = QFrame()
        self.video_frame.setWindowTitle(f"[DEFAULT] Video Player - {os.path.basename(self.video_path)}")
        self.video_frame.setMinimumSize(700, 700)
        self.video_frame.showFullScreen()

        # Set the window handle differently depending on the platform
        if sys.platform == "darwin":  # macOS
            self.mediaplayer.set_nsobject(int(self.video_frame.winId()))
        elif sys.platform == "win32":  # Windows
            self.mediaplayer.set_hwnd(self.video_frame.winId())
        else:  # Linux
            self.mediaplayer.set_xwindow(self.video_frame.winId())

        # Play initial video in main thread
        self.play_in_main_thread()

        return self.app.exec()

#API ----------------------------------------------------------------------------------------------

@app.route('/resume', methods=['POST'])
def resume():
    global current_player

    if not current_player:
        return jsonify({"error": "Video player not initialized"}), 500

    # In the fixed code, we call play() which will emit the signal
    if current_player.play():
        return jsonify({"status": "success", "message": "Resuming"})
    else:
        return jsonify({"error": "Failed to start playback"})

@app.route("/changeVideo", methods=['POST'])
def changeVideo():
    global current_player

    try:
        data = request.get_json(force=True)
        print("Received data:", data.get("serial-number"))
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        return jsonify({"error": "Invalid JSON data"}), 400
    id = data.get("video-id")
    if current_player:
        if current_player.change_video(f"{MAIN_PATH}/{VIDEOS[id]}"):
            return jsonify({"status": "success", "message": "Change video request sent"})
        else:
            return jsonify({"error": "Failed to send change video request"})
    return jsonify({"error": "Video player not initialized"}), 500

@app.route('/play', methods=['POST'])
def play_video():
    global current_player

    try:
        data = request.get_json(force=True)
        print("Received data for play:", data)
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        data = {}

    if not current_player:
        return jsonify({'error': 'Video player not initialized'}), 500

    if 'video_path' in data:
        video_path = data['video_path']

        # Check if file exists
        if not os.path.exists(video_path):
            return jsonify({'error': 'Video file not found'}), 404

        # Change video and play
        if current_player.change_video(video_path):
            return jsonify({'status': 'success', 'message': f'Play request sent for {video_path}'}), 200
        else:
            return jsonify({'error': 'Failed to send play request'}), 500
    else:
        # Just play the current video
        if current_player.play():
            return jsonify({'status': 'success', 'message': 'Play request sent'}), 200
        else:
            return jsonify({'error': 'Failed to send play request'}), 500

@app.route('/pause', methods=['POST'])
def pause_video():
    global current_player

    if current_player:
        if current_player.pause():
            return jsonify({'status': 'success', 'message': 'Pause request sent'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Failed to send pause request'}), 400
    return jsonify({'status': 'error', 'message': 'Video player not initialized'}), 500

@app.route('/stop', methods=['POST'])
def stop_video():
    global current_player

    if current_player:
        if current_player.stop():
            return jsonify({'status': 'success', 'message': 'Stop request sent'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Failed to send stop request'}), 400
    return jsonify({'status': 'error', 'message': 'Video player not initialized'}), 500

@app.route('/close', methods=['POST'])
def close_player():
    global current_player

    if current_player:
        if current_player.close():
            return jsonify({'status': 'success', 'message': 'Close request sent'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Failed to send close request'}), 500
    return jsonify({'status': 'error', 'message': 'Video player not initialized'}), 500

# Add a simple GET endpoint for testing
@app.route('/test', methods=['GET'])
def test_endpoint():
    return jsonify({"status": "API is running"}), 200

def start_flask():
    app.run(host='0.0.0.0', port=5555, debug=False, threaded=True)

def main():
    global current_player

    # Initialize video player
    current_player = VideoPlayer(DEFAULT_VIDEO)

    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=start_flask)
    flask_thread.daemon = True  # Thread will exit when main program exits
    flask_thread.start()

    # Give Flask a moment to start
    time.sleep(1)
    print("Flask server should be running now")

    # Start Qt application in the main thread
    sys.exit(current_player.vlcApp())

if __name__ == '__main__':
    main()
