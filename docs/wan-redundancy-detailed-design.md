# WAN拠点間 冗長化ネットワーク 詳細設計書

- **対象トポロジー**: [`wan_gre_mpls_redundancy.yml`](../wan_gre_mpls_redundancy.yml)
- **版数**: 1.0
- **前提**: [基本設計書](./wan-redundancy-basic-design.md) で定めた方針を、実際のIPアドレス・インターフェース・ルーティングパラメータ・コンフィグまで落とし込み、実機検証で得られた結果とあわせて記録する。

## 目次

1. [IPアドレス設計](#1-ipアドレス設計)
2. [インターフェース設計](#2-インターフェース設計)
3. [ルーティング設計](#3-ルーティング設計)
4. [VPN（GRE over IPsec）設計](#4-vpngre-over-ipsec設計)
5. [コンフィグ抜粋](#5-コンフィグ抜粋)
6. [試験項目・結果](#6-試験項目結果)
7. [運用手順](#7-運用手順)

## 1. IPアドレス設計

| セグメント | ネットワーク | 用途 | 主要IP |
|---|---|---|---|
| Loopback0（router-id） | `/32` 個別 | OSPF/LDP router-id | `WAN-RT1=1.1.1.1` / `P1=2.2.2.2` / `WAN-RT2=3.3.3.3` |
| 拠点A LAN | `10.10.1.0/24` | 拠点A内部セグメント | `WAN-RT1 Gi0/0=.1`, `PC-A=.10` |
| 拠点B LAN | `10.10.2.0/24` | 拠点B内部セグメント | `WAN-RT2 Gi0/0=.1`, `PC-B=.10` |
| MPLS区間（RT1-P1） | `10.99.1.0/30` | プライマリ経路 P2P | `WAN-RT1 Gi0/1=.1`, `P1 Gi0/0=.2` |
| MPLS区間（P1-RT2） | `10.99.2.0/30` | プライマリ経路 P2P | `P1 Gi0/1=.1`, `WAN-RT2 Gi0/1=.2` |
| INET_Core（VPN対向） | `203.0.113.0/24` | GREトンネルのsource/destination | `WAN-RT1 Gi0/2=.1`, `WAN-RT2 Gi0/2=.2` |
| Tunnel0（GRE） | `172.31.0.0/30` | バックアップ経路 論理P2P | `WAN-RT1=.1`, `WAN-RT2=.2` |

## 2. インターフェース設計

| 機器 | インターフェース | IPアドレス | 用途 |
|---|---|---|---|
| `WAN-RT1` | `Lo0` | `1.1.1.1/32` | router-id |
| `WAN-RT1` | `Gi0/0` | `10.10.1.1/24` | 拠点A LAN |
| `WAN-RT1` | `Gi0/1` | `10.99.1.1/30` | 🔵 MPLS → P1 |
| `WAN-RT1` | `Gi0/2` | `203.0.113.1/24` | GREトンネルsource |
| `WAN-RT1` | `Tunnel0` | `172.31.0.1/30` | 🟠 VPN → WAN-RT2 |
| `P1` | `Gi0/0` | `10.99.1.2/30` | MPLS → WAN-RT1 |
| `P1` | `Gi0/1` | `10.99.2.1/30` | MPLS → WAN-RT2 |
| `WAN-RT2` | `Lo0` | `3.3.3.3/32` | router-id |
| `WAN-RT2` | `Gi0/0` | `10.10.2.1/24` | 拠点B LAN |
| `WAN-RT2` | `Gi0/1` | `10.99.2.2/30` | 🔵 MPLS → P1 |
| `WAN-RT2` | `Gi0/2` | `203.0.113.2/24` | GREトンネルsource |
| `WAN-RT2` | `Tunnel0` | `172.31.0.2/30` | 🟠 VPN → WAN-RT1 |

## 3. ルーティング設計

### 3.1 OSPF

単一エリア（area 0）構成。全区間（LAN・MPLS区間・Loopback・Tunnel0）を `network` 文で area 0 に収容する。

| 区間 | コスト | 備考 |
|---|---|---|
| WAN-RT1 ⇔ P1 ⇔ WAN-RT2（物理リンク） | デフォルト（合計約3） | 🔵 プライマリ、平常時はこちらを選択 |
| Tunnel0（GRE/VPN） | `1000`（明示設定） | 🟠 バックアップ、MPLS経路断時のみ選択 |

### 3.2 MPLS / LDP

- WAN-RT1 `Gi0/1`、P1 `Gi0/0`・`Gi0/1`、WAN-RT2 `Gi0/1` に `mpls ip` を設定し、区間全体でラベルスイッチングを有効化。
- `mpls label protocol ldp` / `mpls ldp router-id Loopback0 force` によりLDP router-idをLoopback0に固定。

## 4. VPN（GRE over IPsec）設計

| パラメータ | 設定値 |
|---|---|
| ISAKMP Policy | `encryption aes 256` / `hash sha256` / `authentication pre-share` / `group 14` |
| 事前共有鍵 | 対向IP（203.0.113.1 ⇔ 203.0.113.2）ごとに個別設定 |
| Transform-set | `esp-aes 256` + `esp-sha256-hmac` / `mode transport` |
| IPsec Profile | `GRE-PROTECT`（Tunnel0へ `tunnel protection ipsec profile` で適用） |
| トンネル種別 | GRE（`tunnel source Gi0/2` / `tunnel destination` 対向Gi0/2） |

> GREでルーティングプロトコル（OSPF）をそのまま透過できるため、VPN区間もMPLS区間と同一のOSPFプロセスに収容でき、経路制御をコスト値のみに一元化できる。

## 5. コンフィグ抜粋

WAN-RT1の実投入コンフィグ（抜粋）。WAN-RT2は拠点・対向アドレスを読み替えた対称構成。

```
hostname WAN-RT1
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
interface GigabitEthernet0/1
 ip address 10.99.1.1 255.255.255.252
 mpls ip
interface GigabitEthernet0/2
 ip address 203.0.113.1 255.255.255.0
! --- VPN (GRE over IPsec) ---
crypto isakmp policy 10
 encryption aes 256
 hash sha256
 authentication pre-share
 group 14
crypto isakmp key VpnKey2026 address 203.0.113.2
crypto ipsec transform-set TS esp-aes 256 esp-sha256-hmac
 mode transport
crypto ipsec profile GRE-PROTECT
 set transform-set TS
interface Tunnel0
 ip address 172.31.0.1 255.255.255.252
 tunnel source GigabitEthernet0/2
 tunnel destination 203.0.113.2
 tunnel protection ipsec profile GRE-PROTECT
 ip ospf cost 1000
! --- MPLS / OSPF ---
mpls label protocol ldp
mpls ldp router-id Loopback0 force
router ospf 1
 network 1.1.1.1 0.0.0.0 area 0
 network 10.10.1.0 0.0.0.255 area 0
 network 10.99.1.0 0.0.0.3 area 0
 network 172.31.0.0 0.0.0.3 area 0
```

全文は [`wan_gre_mpls_redundancy.yml`](../wan_gre_mpls_redundancy.yml) の各ノードの `config:` を参照。

## 6. 試験項目・結果

GNS3実機（IOSv）にて全項目を実施済み。試験7〜11は WAN-RT1 の `Gi0/1`（MPLS区間）を意図的に `shutdown` して障害を模擬し、フェイルオーバー/フェイルバックの自動性を確認した。

| No | 試験項目 | 期待結果 | 実施結果 | 判定 |
|---|---|---|---|---|
| 1 | WAN-RT1 `show ip ospf neighbor` | P1・WAN-RT2の両方がFULL | P1(Gi0/1)FULL/DR、WAN-RT2(Tunnel0)FULL | ✅ 合格 |
| 2 | WAN-RT1 `show mpls ldp neighbor` | P1とLDP隣接確立 | Peer 2.2.2.2、State: Oper | ✅ 合格 |
| 3 | `show crypto isakmp sa` | ISAKMP SAがACTIVE | 203.0.113.1⇔.2 双方向 QM_IDLE ACTIVE | ✅ 合格 |
| 4 | `show crypto ipsec sa` | ESPのSAがACTIVE | inbound/outbound esp sa 共にACTIVE | ✅ 合格 |
| 5 | 平常時の経路選択（`show ip route 10.10.2.0`） | 🔵 MPLS（Gi0/1）経由 | metric 3、Gi0/1経由 | ✅ 合格 |
| 6 | PC-A → PC-B ping（平常時） | 5/5成功 | 5/5成功（2〜6ms） | ✅ 合格 |
| 7 | WAN-RT1 `Gi0/1` を `shutdown`（障害注入） | — | 実施 | 🟠 実施 |
| 8 | 障害後の経路再確認 | 🟠 VPN（Tunnel0）へ自動切替 | metric 1001、Tunnel0経由へ切替 | ✅ 合格 |
| 9 | PC-A → PC-B ping（障害時） | VPN経由で継続成功 | 5/5成功（3〜4ms） | ✅ 合格 |
| 10 | WAN-RT1 `Gi0/1` を `no shutdown`（復旧） | — | 実施 | 🔵 実施 |
| 11 | 復旧後の経路再確認 | MPLS経路（Gi0/1）へ自動復帰 | metric 3、Gi0/1経由に復帰 | ✅ 合格 |

**サマリ**

| 指標 | 結果 |
|---|---|
| 試験項目 合格 | **11 / 11** |
| metric（平常時 → フェイルオーバー後） | `3` → `1001` |
| 障害中の通信断（ping失敗） | **0件** |

## 7. 運用手順

### 7.1 経路状態の確認

```
show ip ospf neighbor        ! 両経路の隣接状態を確認
show ip route 10.10.2.0      ! 現在選択中の経路(Gi0/1 or Tunnel0)を確認
show mpls ldp neighbor       ! MPLS区間のLDP隣接を確認
show crypto isakmp sa
show crypto ipsec sa         ! VPN区間のIPsec SA状態を確認
```

### 7.2 想定される運用シナリオ

- **MPLS区間の物理障害**: OSPFが自動的にTunnel0経由へ切替。追加操作は不要。復旧後も自動でフェイルバックする。
- **VPN区間の障害（ISP障害等）**: バックアップ経路のため通信影響はないが、`show crypto isakmp sa` が確立しない場合はPSK・対向IP設定を確認する。
- **意図的な切替試験**: 対象区間のインターフェースを `shutdown` し、`show ip route` で切替を確認後、`no shutdown` で復旧する（本書 6章と同一手順）。

---

前段は [基本設計書](./wan-redundancy-basic-design.md) を参照。
