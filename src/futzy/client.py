class Client:
    
    def __init__(self, **args):
        from Queue import Queue
        self.port = args.get('port', 6000)
        commands = Queue()
        self.commands = commands

    def __enter__(self):
        self.connect()

    def __exit__(self, type, value, traceback):
        self.close()

    def close(self):
        # Special signal for done.
        self.commands.put(None)

    def connect(self):
        from threading import Thread
        commands = self.commands
        # The init won't actually get sent until command get below.
        self.greet()

        def chat():
            from errno import EAGAIN
            from Queue import Empty
            from socket import AF_INET, error, SOCK_DGRAM, socket
            sock = socket(AF_INET, SOCK_DGRAM)
            try:
                # Set up.
                sock.setblocking(False)
                sock.bind(('', 0))
                self.sock = sock

                # Main loop.
                while True:
                    # Look for outbound commands.
                    try:
                        command = commands.get_nowait()
                        if command is None:
                            # Special signal for done.
                            break
                        else:
                            sock.sendto(command, ('127.0.0.1', self.port))
                    except Empty:
                        pass

                    # Look for inbound updates from server.
                    # Should be nonblocking.
                    # Sample rcssclient uses buffer size 8192.
                    try:
                        data = sock.recvfrom(8192)
                        print data
                    except error as err:
                        # EAGAIN just means data wasn't ready. With the server
                        # flood as the common case, this shouldn't happen often.
                        if err.errno == EAGAIN:
                            continue
                        else:
                            raise
                    print data

                print "All done!"

            finally:
                sock.close()

        thread = Thread(target = chat)
        thread.start()

    def send(self, message):
        self.commands.put(message)


class PlayerClient(Client):
    
    def __init__(self, **args):
        Client.__init__(self, **args)
        # TODO Validate team name?
        self.team = args.get('team', 'team')
        
    def greet(self):
        # TODO Escapes on team name?
        self.send('(init %s (version 15))' % self.team)
        #from time import sleep
        #sleep(1.0)
        #self.send('(move -10 10)')
