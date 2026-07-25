# 2拠点間 IPsec + GRE(OSPF) 接続ネットワーク 詳細設計書

- **対象トポロジー**: [`ipsec_gre_ospf_topology.yml`](../examples/ipsec_gre_ospf_topology.yml)
- **版数**: 1.0
- **前提**: [基本設計書](./ipsec-gre-ospf-basic-design.md) で定めた方針を、実際のIPアドレス・
  インターフェース・ルーティングパラメータ・コンフィグまで落とし込む。デプロイ・検証の
  実施手順は [構築手順書](./ipsec-gre-ospf-construction-guide.md) を参照。

## 目次

1. [IPアドレス設計](#1-ipアドレス設計)
2. [インターフェース設計](#2-インターフェース設計)
3. [ルーティング設計](#3-ルーティング設計)
4. [VPN（IPsec + GRE）設計](#4-vpnipsec--gre設計)
5. [コンフィグ抜粋](#5-コンフィグ抜粋)
6. [試験項目（計画）](#6-試験項目計画)
7. [運用手順](#7-運用手順)

## 1. IPアドレス設計

| セグメント | ネットワーク | 用途 | 主要IP |
|---|---|---|---|
| Loopback0（router-id） | `/32` 個別 | OSPF router-id | `WAN-RT-A=1.1.1.1` / `WAN-RT-B=2.2.2.2` |
| INET共有セグメント | `203.0.113.0/24` | IPsec対向・GREトンネルのsource/destination | `WAN-RT-A Gi0/1=.1`, `WAN-RT-B Gi0/1=.2` |
| Tunnel0（GRE） | `172.31.0.0/30` | 拠点間論理P2P（OSPF区間） | `WAN-RT-A=.1`, `WAN-RT-B=.2` |
| 拠点A: WAN-RT-A ⇔ ACCESS-RT-A | `10.10.1.0/30` | 拠点A内トランジット | `WAN-RT-A Gi0/0=.1`, `ACCESS-RT-A Gi0/0=.2` |
| 拠点A: Hostセグメント | `10.20.1.0/24` | host収容（OSPF広告） | `ACCESS-RT-A Gi0/1=.1`, `Host-A=.10` |
| 拠点A: Serverセグメント | `10.30.1.0/24` | server収容（static route） | `ACCESS-RT-A Gi0/2=.1`, `Server-A=.10` |
| 拠点B: WAN-RT-B ⇔ ACCESS-RT-B | `10.10.2.0/30` | 拠点B内トランジット | `WAN-RT-B Gi0/0=.1`, `ACCESS-RT-B Gi0/0=.2` |
| 拠点B: Hostセグメント | `10.20.2.0/24` | host収容（OSPF広告） | `ACCESS-RT-B Gi0/1=.1`, `Host-B=.10` |
| 拠点B: Serverセグメント | `10.30.2.0/24` | server収容（static route） | `ACCESS-RT-B Gi0/2=.1`, `Server-B=.10` |

## 2. インターフェース設計

| 機器 | インターフェース | IPアドレス | 用途 |
|---|---|---|---|
| `WAN-RT-A` | `Lo0` | `1.1.1.1/32` | router-id |
| `WAN-RT-A` | `Gi0/0` | `10.10.1.1/30` | ACCESS-RT-Aへの拠点内リンク |
| `WAN-RT-A` | `Gi0/1` | `203.0.113.1/24` | IPsec対向・GREトンネルsource |
| `WAN-RT-A` | `Tunnel0` | `172.31.0.1/30` | GRE → WAN-RT-B |
| `ACCESS-RT-A` | `Gi0/0` | `10.10.1.2/30` | WAN-RT-Aへの上流リンク |
| `ACCESS-RT-A` | `Gi0/1` | `10.20.1.1/24` | 🟢 Hostセグメント（OSPF） |
| `ACCESS-RT-A` | `Gi0/2` | `10.30.1.1/24` | 🟠 Serverセグメント（static） |
| `WAN-RT-B` | `Lo0` | `2.2.2.2/32` | router-id |
| `WAN-RT-B` | `Gi0/0` | `10.10.2.1/30` | ACCESS-RT-Bへの拠点内リンク |
| `WAN-RT-B` | `Gi0/1` | `203.0.113.2/24` | IPsec対向・GREトンネルsource |
| `WAN-RT-B` | `Tunnel0` | `172.31.0.2/30` | GRE → WAN-RT-A |
| `ACCESS-RT-B` | `Gi0/0` | `10.10.2.2/30` | WAN-RT-Bへの上流リンク |
| `ACCESS-RT-B` | `Gi0/1` | `10.20.2.1/24` | 🟢 Hostセグメント（OSPF） |
| `ACCESS-RT-B` | `Gi0/2` | `10.30.2.1/24` | 🟠 Serverセグメント（static） |

## 3. ルーティング設計

### 3.1 OSPF（area 0、単一エリア）

`network` 文に含める区間と含めない区間を明確に分ける。

| 区間 | OSPF network文 | 備考 |
|---|---|---|
| Loopback0 | ✅ 含める | router-id用 |
| WAN-RT ⇔ ACCESS-RT間トランジット（`10.10.*.0/30`） | ✅ 含める | 拠点内バックボーン |
| Tunnel0（`172.31.0.0/30`） | ✅ 含める | 拠点間の主経路 |
| Hostセグメント（`10.20.*.0/24`） | ✅ 含める | 🟢 動的広告（要件④） |
| INET区間（`203.0.113.0/24`） | ❌ 含めない | 公衆網区間をIGPに含めない（バックドア経路防止） |
| Serverセグメント（`10.30.*.0/24`） | ❌ 含めない | 🟠 static routeで管理（要件⑤） |

### 3.2 Serverセグメントのstatic route + redistribute

ACCESS-RTはServerセグメントに直接接続しているため、ACCESS-RT自身には追加の経路設定は
不要（`connected`経路がそのまま使われる）。到達性は次の2段構えで確保する。

1. **WAN-RTにstatic routeを1本追加**（ACCESS-RTを次ホップとする）

   ```
   ! WAN-RT-A
   ip route 10.30.1.0 255.255.255.0 10.10.1.2
   ! WAN-RT-B
   ip route 10.30.2.0 255.255.255.0 10.10.2.2
   ```

2. **WAN-RTのOSPFプロセスで `redistribute static subnets`** を設定し、上記static routeを
   OSPF外部経路（`O E2`）として対向拠点へ再配布する。

   ```
   router ospf 1
    redistribute static subnets
   ```

この結果、拠点Bから見た `10.30.1.0/24`（Server-A）はOSPFの `show ip route` 上で `O E2` として
学習される（Hostセグメントの `O`＝エリア内経路とは種別が異なる）。

### 3.3 OSPFネイバー構成

| 隣接関係 | インターフェース | ネットワークタイプ |
|---|---|---|
| `WAN-RT-A` ⇔ `WAN-RT-B` | Tunnel0（GRE） | Point-to-Point（GREトンネルのデフォルト） |
| `WAN-RT-A` ⇔ `ACCESS-RT-A` | Gi0/0（両側） | Broadcast（デフォルト、DR/BDR選出あり） |
| `WAN-RT-B` ⇔ `ACCESS-RT-B` | Gi0/0（両側） | Broadcast（デフォルト、DR/BDR選出あり） |

## 4. VPN（IPsec + GRE）設計

| パラメータ | 設定値 |
|---|---|
| ISAKMP Policy | `encryption aes 256` / `hash sha256` / `authentication pre-share` / `group 14` |
| 事前共有鍵 | 対向IP（`203.0.113.1` ⇔ `203.0.113.2`）ごとに個別設定（`VpnKey2026`） |
| Transform-set | `esp-aes 256` + `esp-sha256-hmac` / `mode transport` |
| IPsec Profile | `GRE-PROTECT`（Tunnel0へ `tunnel protection ipsec profile` で適用） |
| トンネル種別 | GRE（`tunnel source Gi0/1` / `tunnel destination` は対向のGi0/1アドレス） |

> GRE上でOSPFがそのまま透過するため、拠点間の経路交換はOSPFプロセス1つに一元化できる。
> IPsecはGREペイロードの暗号化のみを担当し、経路計算には関与しない。

## 5. コンフィグ抜粋

`WAN-RT-A` の実投入コンフィグ（抜粋）。`WAN-RT-B` は拠点・対向アドレスを読み替えた対称構成。

```
hostname WAN-RT-A
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
interface GigabitEthernet0/0
 ip address 10.10.1.1 255.255.255.252
interface GigabitEthernet0/1
 ip address 203.0.113.1 255.255.255.0
! --- VPN (IPsec) ---
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
! --- GRE ---
interface Tunnel0
 ip address 172.31.0.1 255.255.255.252
 tunnel source GigabitEthernet0/1
 tunnel destination 203.0.113.2
 tunnel protection ipsec profile GRE-PROTECT
! --- Serverセグメントへのstatic route ---
ip route 10.30.1.0 255.255.255.0 10.10.1.2
! --- OSPF ---
router ospf 1
 network 1.1.1.1 0.0.0.0 area 0
 network 10.10.1.0 0.0.0.3 area 0
 network 172.31.0.0 0.0.0.3 area 0
 redistribute static subnets
```

`ACCESS-RT-A` の実投入コンフィグ（抜粋）。

```
hostname ACCESS-RT-A
interface GigabitEthernet0/0
 ip address 10.10.1.2 255.255.255.252
interface GigabitEthernet0/1
 ip address 10.20.1.1 255.255.255.0
interface GigabitEthernet0/2
 ip address 10.30.1.1 255.255.255.0
router ospf 1
 network 10.10.1.0 0.0.0.3 area 0
 network 10.20.1.0 0.0.0.255 area 0
```

全文は [`ipsec_gre_ospf_topology.yml`](../examples/ipsec_gre_ospf_topology.yml) の各ノードの
`config:` を参照。

## 6. 試験項目（計画）

以下はGNS3実機での検証を想定した試験計画である。**本書作成時点では未実施**。実施結果は
実際にデプロイ・検証したうえで本表を更新すること（実施方法は
[構築手順書](./ipsec-gre-ospf-construction-guide.md)を参照）。

| No | 試験項目 | 実施箇所 | 期待結果 |
|---|---|---|---|
| 1 | `show crypto isakmp sa` | `WAN-RT-A` | `203.0.113.1` ⇔ `203.0.113.2` 間のISAKMP SAが `QM_IDLE` / `ACTIVE` |
| 2 | `show crypto ipsec sa` | `WAN-RT-A` | Tunnel0向けのESP SA（inbound/outbound）が確立している |
| 3 | `show ip ospf neighbor` | `WAN-RT-A` | Tunnel0経由で `WAN-RT-B`（router-id `2.2.2.2`）がFULL |
| 4 | `show ip ospf neighbor` | `ACCESS-RT-A` | Gi0/0経由で `WAN-RT-A` がFULL |
| 5 | `show ip route` | `WAN-RT-A` | `10.20.2.0/24`（Host-B）が `O`（エリア内経路）で見える |
| 6 | `show ip route` | `WAN-RT-A` | `10.30.2.0/24`（Server-B）が `O E2`（再配布されたstatic経路）で見える |
| 7 | `ping` | `Host-A` → `Host-B` | 成功（拠点間、OSPFで学習した経路） |
| 8 | `ping` | `Host-A` → `Server-B` | 成功（拠点間、static route再配布経由） |
| 9 | `ping` | `Server-A` → `Server-B` | 成功（server同士、双方ともstatic route再配布経由） |
| 10 | `show ip route static` | `ACCESS-RT-A` | Serverセグメント（`10.30.1.0/24`）は`connected`として見え、staticエントリ自体はACCESS-RT側には存在しない（WAN-RT側で管理） |

## 7. 運用手順

### 7.1 状態確認コマンド

```
show crypto isakmp sa           ! IKE SAの状態
show crypto ipsec sa            ! ESP SAの状態（IPsecの実疎通）
show ip ospf neighbor           ! OSPFネイバー状態（Tunnel0 / Gi0/0双方）
show ip route                   ! O(エリア内) / O E2(再配布static) の区別を確認
show ip route static            ! WAN-RTに設定したserver向けstatic routeの確認
```

### 7.2 想定される障害切り分け

- **IPsec SAが確立しない**: 事前共有鍵・対向IP（`203.0.113.1`/`.2`）・ISAKMP policyの
  パラメータ不一致を疑う。`crypto isakmp key` のaddress指定と実際の対向Gi0/1アドレスが
  一致しているか確認する。
- **OSPFネイバーがTunnel0で上がらない**: IPsec SAが未確立の場合、GREパケット自体が
  暗号化できず疎通しないため、まず7.1のIPsec状態を確認する。IPsecが正常でもネイバーが
  上がらない場合はTunnel0の`ip address`が同一サブネットか、`network`文のワイルドカード
  マスクが正しいかを確認する。
- **拠点間でServerセグメントに到達できない**: WAN-RTの`ip route`（次ホップ=ACCESS-RTの
  上流IP）と、OSPFプロセスの`redistribute static subnets`の両方が設定されているか確認する。
  `subnets`キーワードを付け忘れると `/24` のようなサブネット化された経路が再配布されない。
- **拠点間でHostセグメントに到達できない**: ACCESS-RTのOSPF `network`文にHostセグメントの
  サブネットが含まれているか、WAN-RT-ACCESS-RT間のトランジット区間でOSPFネイバーが
  FULLになっているかを確認する。

---

前段は [基本設計書](./ipsec-gre-ospf-basic-design.md)、
実際の構築手順は [構築手順書](./ipsec-gre-ospf-construction-guide.md) を参照。
