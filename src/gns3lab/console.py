"""ノード起動後にコンソール (telnet) 経由でCLI設定を自動投入するための最小限のクライアント。

GNS3のREST APIには dynamips/IOU などのCLI型ノードに設定を流し込む専用エンドポイントが
存在しないため、実機と同じくコンソールに接続してコマンドを打鍵する方式で代替する。
タイミング依存のexpectスクリプトであり、全ての機種・全ての状況を保証するものではない。
"""

import socket
import time
from urllib.parse import urlparse

IAC = 0xFF
DONT = 0xFE
DO = 0xFD
WONT = 0xFC
WILL = 0xFB
SB = 0xFA
SE = 0xF0

IOS_BOOT_TIMEOUT = 180
CONNECT_TIMEOUT = 10


class ConsoleError(RuntimeError):
    pass


class MiniTelnet:
    """telnetオプション折衝の最低限だけを処理する簡易telnetクライアント。

    標準ライブラリの telnetlib は Python 3.13 で削除されたため使用しない。
    """

    def __init__(self, host, port, timeout=CONNECT_TIMEOUT):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(1)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def write(self, text):
        self.sock.sendall(text.encode("utf-8", errors="replace"))

    def write_line(self, text):
        self.write(text + "\r\n")

    def _strip_iac(self, data):
        out = bytearray()
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == IAC and i + 1 < n:
                cmd = data[i + 1]
                if cmd in (DO, DONT, WILL, WONT) and i + 2 < n:
                    opt = data[i + 2]
                    reply = WONT if cmd == DO else (DONT if cmd == WILL else None)
                    if reply is not None:
                        try:
                            self.sock.sendall(bytes([IAC, reply, opt]))
                        except OSError:
                            pass
                    i += 3
                    continue
                if cmd == SB:
                    end = data.find(bytes([IAC, SE]), i)
                    i = end + 2 if end != -1 else n
                    continue
                i += 2
                continue
            out.append(b)
            i += 1
        return bytes(out)

    def expect(self, patterns, timeout):
        """いずれかの patterns が現れるまで読み続ける。(一致した文字列 or None, 受信内容)"""
        deadline = time.time() + timeout
        seen = ""
        while time.time() < deadline:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            seen += self._strip_iac(chunk).decode("utf-8", errors="replace")
            for p in patterns:
                if p in seen:
                    return p, seen
        return None, seen


def get_console_host(base, node):
    console_host = node.get("console_host")
    if console_host and console_host not in ("0.0.0.0", "::", ""):
        return console_host
    return urlparse(base).hostname


def push_node_config(base, node, node_def, config_text):
    host = get_console_host(base, node)
    port = node.get("console")
    if not host or not port:
        raise ConsoleError("console のホスト/ポートが取得できません")

    node_type = node.get("node_type", "")
    if node_type in ("dynamips", "iou"):
        _push_ios_config(host, port, config_text, node_def.get("enable_password"))
    elif node_type == "vpcs":
        _push_vpcs_config(host, port, config_text)
    else:
        raise ConsoleError(f"node_type={node_type!r} の自動設定投入には未対応です")


def _push_ios_config(host, port, config_text, enable_password=None):
    tn = MiniTelnet(host, port)
    try:
        deadline = time.time() + IOS_BOOT_TIMEOUT
        ready = False
        while time.time() < deadline and not ready:
            pattern, _ = tn.expect(["[yes/no]:", "Press RETURN", ">", "#"], timeout=5)
            if pattern is None:
                tn.write("\r\n")
            elif pattern == "[yes/no]:":
                tn.write_line("no")
            elif pattern == "Press RETURN":
                tn.write("\r\n")
            else:
                ready = True
        if not ready:
            raise ConsoleError("起動プロンプトを検出できませんでした (タイムアウト)")

        tn.write_line("enable")
        pattern, _ = tn.expect(["Password:", "#"], timeout=5)
        if pattern == "Password:":
            if not enable_password:
                raise ConsoleError(
                    "enable パスワードを要求されましたが node の enable_password が未設定です"
                )
            tn.write_line(enable_password)
            pattern, _ = tn.expect(["#"], timeout=5)
            if pattern is None:
                raise ConsoleError("enable に失敗しました (パスワード相違の可能性)")

        tn.write_line("terminal length 0")
        tn.expect(["#"], timeout=5)

        tn.write_line("configure terminal")
        pattern, _ = tn.expect(["(config)#"], timeout=5)
        if pattern is None:
            raise ConsoleError("configure terminal に入れませんでした")

        for line in config_text.splitlines():
            line = line.strip()
            if not line or line.startswith("!"):
                continue
            tn.write_line(line)
            time.sleep(0.15)

        tn.write_line("end")
        tn.expect(["#"], timeout=5)
        tn.write_line("write memory")
        tn.expect(["[OK]", "#"], timeout=15)
    finally:
        tn.close()


def _push_vpcs_config(host, port, config_text):
    tn = MiniTelnet(host, port)
    try:
        tn.expect([">"], timeout=15)
        for line in config_text.splitlines():
            line = line.strip()
            if not line:
                continue
            tn.write_line(line)
            time.sleep(0.2)
    finally:
        tn.close()
