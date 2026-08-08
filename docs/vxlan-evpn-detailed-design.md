# VXLAN/EVPN ファブリック検証ネットワーク 詳細設計書

- **対象トポロジー**: [`vxlan_evpn_topology.yml`](../examples/vxlan_evpn_topology.yml)
- **版数**: 1.0
- **前提**: [基本設計書](./vxlan-evpn-basic-design.md) で定めた方針を、実際のIPアドレス・
  インターフェース・ルーティングパラメータ・コンフィグまで落とし込む。

## 目次

1. [IPアドレス設計](#1-ipアドレス設計)
2. [インターフェース設計](#2-インターフェース設計)
3. [Underlay設計（OSPF）](#3-underlay設計ospf)
4. [Overlay設計（BGP EVPN）](#4-overlay設計bgp-evpn)
5. [VXLANデータプレーン設計](#5-vxlanデータプレーン設計)
6. [コンフィグ抜粋](#6-コンフィグ抜粋)
7. [試験項目（計画）](#7-試験項目計画)
8. [運用手順](#8-運用手順)

## 1. IPアドレス設計

| セグメント | ネットワーク | 用途 | 主要IP |
|---|---|---|---|
| SPINE-LEAF1 P2P | `10.255.0.0/30` | Underlay | `SPINE eth0=.1`, `LEAF1 swp1=.2` |
| SPINE-LEAF2 P2P | `10.255.0.4/30` | Underlay | `SPINE eth1=.5`, `LEAF2 swp1=.6` |
| Loopback（Router-ID/VTEP） | `/32` 個別 | OSPF router-id、BGP update-source、VTEP source | `SPINE=10.255.255.100`, `LEAF1=10.255.255.1`, `LEAF2=10.255.255.2` |
| Overlay（VNI 10010） | `192.168.10.0/24` | VXLAN越しにストレッチされるホストセグメント | `PC1=.10`, `PC2=.20` |

## 2. インターフェース設計

| 機器 | インターフェース | IPアドレス | 用途 |
|---|---|---|---|
| `SPINE` | `lo` | `10.255.255.100/32` | Router-ID / BGP update-source |
| `SPINE` | `eth0` | `10.255.0.1/30` | LEAF1向けUnderlay |
| `SPINE` | `eth1` | `10.255.0.5/30` | LEAF2向けUnderlay |
| `LEAF1` | `lo` | `10.255.255.1/32` | Router-ID / VTEPソースIP |
| `LEAF1` | `swp1` | `10.255.0.2/30` | SPINE向けUnderlay |
| `LEAF1` | `swp2` | IPなし（L2ブリッジポート） | PC1収容、`bridge`（VLAN10）のメンバー |
| `LEAF1` | `vni10010` | — | VNI 10010のVXLANインターフェース、`bridge access 10` |
| `LEAF2` | `lo` | `10.255.255.2/32` | Router-ID / VTEPソースIP |
| `LEAF2` | `swp1` | `10.255.0.6/30` | SPINE向けUnderlay |
| `LEAF2` | `swp2` | IPなし（L2ブリッジポート） | PC2収容、`bridge`（VLAN10）のメンバー |
| `LEAF2` | `vni10010` | — | VNI 10010のVXLANインターフェース、`bridge access 10` |
| `PC1` | `eth0` | `192.168.10.10/24` | 検証用ホスト（LEAF1配下） |
| `PC2` | `eth0` | `192.168.10.20/24` | 検証用ホスト（LEAF2配下） |

## 3. Underlay設計（OSPF）

単一エリア0。P2Pリンクと各ノードのLoopbackのみを`network`文に含め、VNI（VXLANの
オーバーレイ側）や`swp2`（ホスト収容ポート）はOSPFに含めない。

| 区間 | OSPF対象 | 備考 |
|---|---|---|
| SPINE-LEAF1 P2P (`10.255.0.0/30`) | ✅ 含める | Underlay backbone |
| SPINE-LEAF2 P2P (`10.255.0.4/30`) | ✅ 含める | Underlay backbone |
| 各ノードのLoopback (`/32`) | ✅ 含める | VTEP/BGP peeringの到達性確保 |
| `swp2`（ホスト収容、VLAN10側） | ❌ 含めない | Overlay側のセグメントなので、Underlay(IGP)には漏らさない |

SPINE側はvtyshの`router ospf`配下で`network`文を個別指定。LEAF側（Cumulus/NCLU）は
インターフェース単位で`net add interface swp1 ospf area 0.0.0.0` / `net add loopback lo ospf
area 0.0.0.0` の形で有効化する（NCLUの標準的な書き方。FRRの`network`文でも代替可）。

## 4. Overlay設計（BGP EVPN）

| パラメータ | 設定値 |
|---|---|
| AS番号 | `65000`（Underlay/Overlayとも単一ASのiBGP構成） |
| Router-ID | 各ノードのLoopbackアドレスと同一 |
| BGPピアリング | Loopback同士（`update-source lo`） |
| Route Reflector | `SPINE`（`neighbor <LEAF> route-reflector-client`） |
| RRクライアント | `LEAF1`, `LEAF2`（NCLU上は`remote-as internal`でiBGPかつSPINE側でRR設定する構成） |
| address-family | `l2vpn evpn` のみ有効化（`no bgp default ipv4-unicast`をSPINEに設定し、Underlay向けの誤ったIPv4-unicastアドバタイズを防止） |
| VNI広告 | 各LEAFで`advertise-all-vni`（保有VNIをEVPN Type-3として自動広告） |

LEAF1・LEAF2はSPINEとのみBGPセッションを張り、LEAF同士は直接ピアリングしない
（Route Reflectorパターン）。EVPNルート（Type-2: MAC/IP、Type-3: Inclusive Multicast）は
すべてSPINE経由で中継される。

## 5. VXLANデータプレーン設計

| 項目 | 値 |
|---|---|
| VNI | `10010` |
| 対応VLAN | `10` |
| ブリッジ | `bridge`（VLANアウェアブリッジ、`vlan-aware`） |
| ブリッジメンバー | `swp2`（ホスト収容ポート）、`vni10010`（VXLANインターフェース） |
| VTEPソース | 各LEAFのLoopback（`local-tunnelip`） |

LEAF1で受信したPC1のフレーム（VLAN10）は、ブリッジを介してVNI 10010にマッピングされ、
LEAF2のLoopback（`10.255.255.2`）宛にVXLANカプセル化されてUnderlay（OSPF区間）を通過し、
LEAF2側で非カプセル化されてPC2へ届く。MACアドレス学習はEVPN Type-2ルートとしてBGP経由でも
交換されるため、Data-Plane Learning（従来のフラッド&ラーン方式のVXLAN）とは異なり、
未知の宛先MACへの通信もEVPNで事前学習したVTEP情報をもとに転送できる。

## 6. コンフィグ抜粋

> ⚠️ Cumulus VX 5.4.0はビルドによりNVUE（`nv add ...`）がデフォルトの場合がある。以下は
> NCLU（`net add ...`）構文を前提とする。`net add`が認識されない場合は `net --help` で
> NCLU互換モードの有無を確認し、必要に応じてNVUE構文（`nv add ...` / `nv config apply`）に
> 読み替えること。

`SPINE`（FRR、vtysh）:

```
configure terminal
interface eth0
 ip address 10.255.0.1/30
interface eth1
 ip address 10.255.0.5/30
interface lo
 ip address 10.255.255.100/32
router ospf
 network 10.255.0.0/30 area 0.0.0.0
 network 10.255.0.4/30 area 0.0.0.0
 network 10.255.255.100/32 area 0.0.0.0
router bgp 65000
 bgp router-id 10.255.255.100
 no bgp default ipv4-unicast
 neighbor 10.255.255.1 remote-as 65000
 neighbor 10.255.255.1 update-source lo
 neighbor 10.255.255.2 remote-as 65000
 neighbor 10.255.255.2 update-source lo
 address-family l2vpn evpn
  neighbor 10.255.255.1 activate
  neighbor 10.255.255.1 route-reflector-client
  neighbor 10.255.255.2 activate
  neighbor 10.255.255.2 route-reflector-client
 exit-address-family
end
write memory
```

`LEAF1`（Cumulus VX、NCLU）。`LEAF2`はLoopback/swp1アドレスを`10.255.255.2`
/`10.255.0.6/30`に読み替えた対称構成。

```
net add loopback lo ip address 10.255.255.1/32
net add interface swp1 ip address 10.255.0.2/30
net add interface swp1 ospf area 0.0.0.0
net add loopback lo ospf area 0.0.0.0
net add bridge bridge vlan-aware
net add bridge bridge ports swp2
net add bridge bridge vids 10
net add vxlan vni10010 vxlan id 10010
net add vxlan vni10010 vxlan local-tunnelip 10.255.255.1
net add vxlan vni10010 bridge access 10
net add bgp autonomous-system 65000
net add bgp router-id 10.255.255.1
net add bgp neighbor 10.255.255.100 remote-as internal
net add bgp neighbor 10.255.255.100 update-source lo
net add bgp l2vpn evpn neighbor 10.255.255.100 activate
net add bgp l2vpn evpn advertise-all-vni
net commit
```

`PC1` / `PC2`（VPCS、自動投入済み）:

```
ip 192.168.10.10 255.255.255.0   ! PC1
ip 192.168.10.20 255.255.255.0   ! PC2
save
```

全文は [`vxlan_evpn_topology.yml`](../examples/vxlan_evpn_topology.yml) の各ノードの
`config:` を参照。

## 7. 試験項目（計画）

以下はGNS3実機での検証を想定した試験計画である。**本書作成時点では未実施**（config手動投入・
疎通確認とも未実施）。実施結果は実際に検証したうえで本表を更新すること。

| No | 試験項目 | 実施箇所 | 期待結果 |
|---|---|---|---|
| 1 | `show ip ospf neighbor`（vtysh） | `SPINE` | LEAF1（`10.255.255.1`）・LEAF2（`10.255.255.2`）双方がFULL |
| 2 | `net show ospf neighbor` | `LEAF1` | SPINE（`10.255.255.100`）がFULL |
| 3 | `show bgp l2vpn evpn summary`（vtysh） | `SPINE` | LEAF1・LEAF2とのEVPNセッションがEstablished |
| 4 | `net show bgp l2vpn evpn summary` | `LEAF1` | SPINEとのEVPNセッションがEstablished |
| 5 | `net show bgp l2vpn evpn vni 10010` | `LEAF1` | LEAF2のVTEP（`10.255.255.2`）がType-3ルート（IMET）として見える |
| 6 | `net show evpn vni 10010` | `LEAF1` | VNI 10010のリモートVTEPとして`10.255.255.2`が登録されている |
| 7 | `ping 192.168.10.20` | `PC1` | 成功（VXLANでカプセル化されたL2通信、LEAF1→LEAF2） |
| 8 | `net show bridge macs` または `bridge fdb show` | `LEAF1` | PC2のMACアドレスがVNI 10010・LEAF2のVTEP経由で学習されている |
| 9 | `show interface eth0`（vtysh） | `SPINE` | インターフェース状態がup、OSPF/BGPどちらの障害でもないことを切り分けられる |

## 8. 運用手順

### 8.1 状態確認コマンド

```
# SPINE (vtysh)
show ip ospf neighbor
show bgp l2vpn evpn summary
show bgp l2vpn evpn route type multicast     ! Type-3 (IMET) ルート一覧

# LEAF1/LEAF2 (Cumulus / NCLU)
net show ospf neighbor
net show bgp l2vpn evpn summary
net show bgp l2vpn evpn vni 10010
net show evpn vni 10010
net show interface vni10010
bridge fdb show
```

### 8.2 想定される障害切り分け

- **OSPFネイバーが上がらない**: `net add interface swp1 ospf area 0.0.0.0` の投入漏れ、
  またはSPINE側`network`文の範囲指定ミス（`10.255.0.0/30`と`10.255.0.4/30`を取り違えていないか）
  を疑う。まずUnderlayが正常であることを確認してからOverlay（BGP）の確認に進むこと。
- **BGP EVPNセッションが張れない**: `update-source lo`の設定漏れでLoopback以外の
  アドレスからセッションを試みていないか確認する。Underlay（OSPF）が正常でLoopback同士が
  pingできることが前提条件になる。
- **VNI 10010のType-3ルートが対向に見えない**: LEAF側の`net add bgp l2vpn evpn
  advertise-all-vni`の投入漏れ、またはSPINE側の`route-reflector-client`設定漏れ
  （RRクライアント指定がないとSPINEはEVPNルートを他のLEAFへ反射しない）を疑う。
- **PC1-PC2間でpingが通らない**: 上記1〜3が正常であることを確認したうえで、
  `net show bridge macs` でお互いのMACアドレスがVNI 10010上に学習されているか確認する。
  ブリッジの`vids 10`設定漏れ、`vni10010`の`bridge access 10`設定漏れが典型的な原因。
- **Cumulus VXで`net add`コマンドが認識されない**: そのビルドがNVUEデフォルトの可能性が
  高い。`net --help`でNCLU互換レイヤの有無を確認し、無い場合は`nv add`構文または
  `/etc/network/interfaces`の直接編集に読み替える。

---

前段は [基本設計書](./vxlan-evpn-basic-design.md) を参照。
