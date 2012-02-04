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
        self.init()

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
                        # Special signal for done.
                        done = command is None
                        if done:
                            # Be nice and say goodbye, but it varies by client
                            # type.
                            command = self.bye()
                        # Send the command out.
                        sock.sendto(command, ('127.0.0.1', self.port))
                        if done:
                            break
                    except Empty:
                        pass

                    # Look for inbound updates from server.
                    # Should be nonblocking.
                    # Sample rcssclient uses buffer size 8192.
                    try:
                        data = sock.recvfrom(8192)
                        self.process(data)
                    except error as err:
                        # EAGAIN just means data wasn't ready. With the server
                        # flood as the common case, this shouldn't happen often.
                        if err.errno == EAGAIN:
                            continue
                        else:
                            raise

            finally:
                sock.close()

        thread = Thread(target = chat)
        thread.start()

    def process(self, data):
        # The sample rcssclient implies that single packets always contain a
        # single message and that it doesn't get chopped off. Just believe that
        # for now.
        #print
        #print data
        pass

    def send(self, message):
        self.commands.put(message)


class PlayerClient(Client):
    
    def __init__(self, **args):
        Client.__init__(self, **args)
        # TODO Validate team name?
        self.team = args.get('team', 'team')

    def bye(self):
        # Players have a simple bye.
        return '(bye)'

    def init(self):
        # TODO Escapes on team name?
        # TODO Support reconnect?
        self.send('(init %s (version 15))' % self.team)
        #from time import sleep
        #sleep(1.0)
        #self.send('(move -10 10)')
