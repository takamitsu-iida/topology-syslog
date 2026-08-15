"""
アラートストームシミュレーター

使い方:
    python test_sender.py [--scenario <1|2>]

    --scenario 1 (デフォルト):
        Core-Router1 を根本原因とする3機器の連鎖障害を送信する。
        期待結果: 1件のインシデント (ROOT CAUSE: Core-Router1)

    --scenario 2:
        上記に加え、無関係な拠点 (Branch-Router2) からのログも混入させる。
        期待結果: 2件の独立したインシデント
"""

import argparse
import socket
import time

SERVER = ("127.0.0.1", 514)


def send(sock: socket.socket, host: str, msg: str) -> None:
    payload = f"Host:{host} {msg}".encode()
    sock.sendto(payload, SERVER)
    print(f"  -> {host}: {msg}")


def scenario1(sock: socket.socket) -> None:
    """Core-Router1 障害による3機器の連鎖アラート"""
    print("[SCENARIO 1] コアルーター障害 (3ノード連鎖)")
    send(sock, "Core-Router1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down")
    time.sleep(0.2)
    send(sock, "Dist-Switch1", "%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Down")
    time.sleep(0.2)
    send(sock, "Access-SW1", "%PING-3-FAILED: Gateway 10.0.0.1 unreachable")
    print("送信完了。10秒後にサーバー側で集約結果が表示されます。\n")


def scenario2(sock: socket.socket) -> None:
    """連鎖障害 + 無関係な拠点のログ混入"""
    print("[SCENARIO 2] コアルーター障害 + 別拠点ノイズ混入 (5ノード)")
    send(sock, "Core-Router1", "%LINK-3-UPDOWN: Interface GigabitEthernet0/0, changed state to down")
    time.sleep(0.2)
    send(sock, "Dist-Switch1", "%BGP-5-ADJCHANGE: neighbor 10.0.0.1 Down")
    time.sleep(0.2)
    send(sock, "Access-SW1", "%PING-3-FAILED: Gateway 10.0.0.1 unreachable")
    time.sleep(0.2)
    # 無関係な別拠点の障害 (独立インシデントとして分離されることを確認)
    send(sock, "Branch-Router2", "%LINK-3-UPDOWN: Interface GigabitEthernet0/1, changed state to down")
    time.sleep(0.2)
    send(sock, "Branch-Access-SW1", "%CDP-4-NATIVE_VLAN_MISMATCH: Native VLAN mismatch")
    print("送信完了。10秒後にサーバー側で2件のインシデントが表示されることを確認してください。\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Syslog アラートストームシミュレーター")
    parser.add_argument("--scenario", type=int, choices=[1, 2], default=1)
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if args.scenario == 1:
            scenario1(sock)
        else:
            scenario2(sock)
    finally:
        sock.close()


if __name__ == "__main__":
    main()
