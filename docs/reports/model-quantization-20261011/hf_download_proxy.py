"""临时 loopback CONNECT 转发，只允许公开 Hugging Face 下载域名。"""
import select
import socket
import socketserver


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        first=self.rfile.readline(4096).decode('ascii')
        method,target,_=first.strip().split(' ',2)
        while self.rfile.readline(4096) not in (b'\r\n',b'\n',b''):
            pass
        host,port=target.rsplit(':',1)
        if method!='CONNECT' or int(port)!=443 or not any(host==d or host.endswith('.'+d)
                                                          for d in ('huggingface.co','hf.co')):
            self.wfile.write(b'HTTP/1.1 403 Forbidden\r\n\r\n')
            return
        with socket.create_connection((host,int(port)),timeout=30) as upstream:
            self.wfile.write(b'HTTP/1.1 200 Connection established\r\n\r\n');self.wfile.flush()
            sockets=[self.connection,upstream]
            while True:
                readable,_,_=select.select(sockets,[],[],60)
                if not readable:return
                for source in readable:
                    data=source.recv(256*1024)
                    if not data:return
                    (upstream if source is self.connection else self.connection).sendall(data)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True


if __name__=='__main__':
    with Server(('127.0.0.1',18973),Handler) as server:
        print('临时 Hugging Face 下载转发已监听本机 loopback:18973',flush=True)
        server.serve_forever()
