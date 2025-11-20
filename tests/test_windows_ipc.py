import unittest
import os
import time
import threading
from pypresence import windows_ipc

class TestWindowsIPC(unittest.TestCase):

    def setUp(self):
        self.pipe_name = r'\\.\pipe\test_pipe'
        self.server_thread = threading.Thread(target=self.start_server)
        self.server_thread.start()
        time.sleep(1)  # Give the server time to start

    def tearDown(self):
        # Clean up the named pipe if it exists
        try:
            os.unlink(self.pipe_name)
        except FileNotFoundError:
            pass

    def start_server(self):
        # Create a named pipe server
        windows_ipc.create_named_pipe(self.pipe_name)

    def test_named_pipe_creation(self):
        # Test if the named pipe was created successfully
        self.assertTrue(windows_ipc.named_pipe_exists(self.pipe_name))

    def test_named_pipe_communication(self):
        # Test sending and receiving data through the named pipe
        message = b'Test message'
        windows_ipc.send_message(self.pipe_name, message)
        received_message = windows_ipc.receive_message(self.pipe_name)
        self.assertEqual(received_message, message)

if __name__ == '__main__':
    unittest.main()