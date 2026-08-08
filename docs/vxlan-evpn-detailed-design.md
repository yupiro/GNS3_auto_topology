# VXLAN/EVPN ファブリック検証ネットワーク 詳細設計書

- **対象トポロジー**: [`vxlan_evpn_topology.yml`](../examples/vxlan_evpn_topology.yml)
- **版数**: 1.1（**GNS3実機検証済み**。検証で判明した注意点を反映）
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

> ⚠️ **GNS3のadapter番号とCumulus VXのswpポート番号は1つズレる**（実機検証で判明）。
> `adapter0`=`eth0`(mgmt)、`adapter1`=`swp1`、`adapter2`=`swp2` ... という対応になる
> （`ip -br link show`のMACアドレス末尾で確認できる。`swp1`のMACは`adapter1`用のもの）。
> `examples/vxlan_evpn_topology.yml`の`links:`はこれを踏まえ`LEAF1:1/0`=swp1、
> `LEAF1:2/0`=swp2としている。

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

> ⚠️ **実機検証の結果、NCLU（`net add ...`）はこのCumulus VX 5.4.0テンプレートでは
> 使用不可**と判明した（`net show`/`net help`のみ動作し、`net add interface/loopback/
> bridge/vxlan/bgp`は「Command not found」）。代替のNVUE（`nv`）もデーモン`nvued`が
> テンプレート既定RAM（1024MB、実効723MB）でOOM Killerに落ちるため使用不可。
> **そのため以降はNCLU/NVUEを使わず、ifupdown2（`/etc/network/interfaces`）+ vtysh を
> 直接使う**（Cumulus LinuxのNCLU/NVUEも内部では同じifupdown2/FRR設定を生成しているだけ
> なので、正規の下位互換手段）。

`SPINE`（FRR、vtysh。ログイン後は自動的にvtyshプロンプトになる）:

```
configure terminal
interface eth0
 ip address 10.255.0.1/30
 ip ospf mtu-ignore
interface eth1
 ip address 10.255.0.5/30
 ip ospf mtu-ignore
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

`ip ospf mtu-ignore` はSPINE(MTU 1500)とLEAF(MTU 9216)のMTU不一致でOSPFネイバーが
`ExStart`から進まなくなる問題への対処（[8.2 障害切り分け](#82-想定される障害切り分け)参照）。

`LEAF1`（Cumulus VX）。まず`/etc/network/interfaces`にL2/L3設定を追記し`ifreload`で反映、
`/etc/frr/daemons`でbgpd/ospfdを有効化してFRRを再起動したうえで、`vtysh`でルーティングを
投入する。`LEAF2`はLoopback/swp1アドレス・`vxlan-local-tunnelip`・`bgp router-id`を
`10.255.255.2`/`10.255.0.6/30`に読み替えた対称構成。

```
# --- 1. ifupdown2 (要sudo) ---
sudo tee -a /etc/network/interfaces << 'EOF'

auto swp1
iface swp1
    address 10.255.0.2/30

auto swp2
iface swp2
    bridge-access 10

auto vni10010
iface vni10010
    vxlan-id 10010
    vxlan-local-tunnelip 10.255.255.1
    bridge-access 10

auto bridge
iface bridge
    bridge-vlan-aware yes
    bridge-ports swp2 vni10010
    bridge-vids 10
EOF
sudo sed -i '/^iface lo inet loopback/a\    address 10.255.255.1/32' /etc/network/interfaces
sudo ifreload -a

# --- 2. FRRデーモン有効化 (bgpd/ospfdはデフォルト無効) ---
sudo sed -i 's/^bgpd=no/bgpd=yes/; s/^ospfd=no/ospfd=yes/' /etc/frr/daemons
sudo systemctl restart frr

# --- 3. vtyshでルーティング投入 ---
sudo vtysh
```
```
configure terminal
interface swp1
 ip ospf area 0.0.0.0
 ip ospf mtu-ignore
interface lo
 ip ospf area 0.0.0.0
router ospf
router bgp 65000
 bgp router-id 10.255.255.1
 no bgp default ipv4-unicast
 neighbor 10.255.255.100 remote-as internal
 neighbor 10.255.255.100 update-source lo
 address-family l2vpn evpn
  neighbor 10.255.255.100 activate
  advertise-all-vni
 exit-address-family
end
write memory
```

`swp2`の`bridge-access 10`は明示しないとデフォルトVLAN1のままになり、VNI 10010（VLAN10）
に乗らずPC間通信が失敗する（[8.2 障害切り分け](#82-想定される障害切り分け)参照）。
`router ospf`のみ（配下にnetwork文なし）で一度エンターすることで、OSPFプロセス自体を
インスタンス化している（interface個別の`ip ospf area`だけではプロセスが起動しなかった）。

`PC1` / `PC2`（VPCS、自動投入済み）:

```
ip 192.168.10.10 255.255.255.0   ! PC1
ip 192.168.10.20 255.255.255.0   ! PC2
save
```

全文は [`vxlan_evpn_topology.yml`](../examples/vxlan_evpn_topology.yml) の各ノードの
`config:` およびヘッダーコメントを参照。

## 7. 試験項目結果

以下はGNS3実機での検証結果である（NCLU不使用・[6章](#6-コンフィグ抜粋)のifupdown2+vtysh
方式で投入）。

| No | 試験項目 | 実施箇所 | 期待結果 | 結果 |
|---|---|---|---|---|
| 1 | `show ip ospf neighbor`（vtysh） | `SPINE` | LEAF1（`10.255.255.1`）・LEAF2（`10.255.255.2`）双方がFULL | ✅ PASS（両者 `Full/Backup`） |
| 2 | `show bgp l2vpn evpn summary`（vtysh） | `SPINE` | LEAF1・LEAF2とのEVPNセッションがEstablished | ✅ PASS（両者Up、PfxRcd=1/PfxSnt=2） |
| 3 | `sudo vtysh -c "show evpn vni 10010"` | `LEAF1` | LEAF2のVTEP（`10.255.255.2`）がリモートVTEPとして見える | ✅ PASS（`Remote VTEPs for this VNI: 10.255.255.2 flood: HER`） |
| 4 | `sudo vtysh -c "show bgp l2vpn evpn route"` | `LEAF1` | Type-3（IMET）ルートとしてLEAF2（`10.255.255.2`）のVTEP情報を受信 | ✅ PASS（RD `10.255.255.2:2` の `[3]:[0]:[32]:[10.255.255.2]` を確認） |
| 5 | `ping 192.168.10.20` | `PC1` | 成功（VXLANでカプセル化されたL2通信、LEAF1→LEAF2） | ✅ PASS（5/5、平均RTT約1.6ms） |
| 6 | `sudo vtysh -c "show evpn vni 10010"` の `Number of MACs` | `LEAF1` | PC1・PC2双方のMACが学習されている | ✅ PASS（ping後に`2`に増加。ping前は`0`） |
| 7 | `ping 10.255.0.2`（Underlay） | `SPINE` シェル | LEAF1のswp1アドレスに到達 | ✅ PASS（0% packet loss） |

## 7.1 検証で判明した問題と対処（トラブルシュート記録）

構築時に5つの問題に遭遇した。いずれも[基本設計書7章](./vxlan-evpn-basic-design.md#7-前提条件制約事項)
にも要点を記載済みだが、発生順に詳細を残す。

1. **NCLU（`net add`）が動作しない** — `net add interface/loopback/bridge/vxlan/bgp`が
   すべて`ERROR: Command not found`。`dpkg -L nclu`で調べたところ、このイメージのNCLU
   プラグインは`dns/dhcp/nat/ntp/ports/snmp/...`等に限られ、L2/L3コア機能のプラグインが
   存在しなかった。代替の`nv`（NVUE）はデーモン`nvued`が`systemctl status`で`failed`。
   `sudo systemctl restart nvued`を試みると`dmesg`に`Out of memory: Killed process
   ... (python3)`と出て即落ちた（RAM 1024MB指定でも実効723MB、空き90MB程度しかなく
   nvuedの必要メモリを満たせない）。→ ifupdown2 + vtysh 直接方式に切替。
2. **sudoパスワードが不明で何も設定できない** — GNS3公式カタログ記載の`cumulus/cumulus`
   はsudoパスワードとしては通らなかった。原因は、この認証情報が本来cloud-init（Vagrant等
   の初回プロビジョニング）経由で設定される前提のもので、GNS3上でqcow2を素のまま起動した
   今回の環境ではcloud-initが一度も走っておらず（`/var/lib/cloud/instance`が存在しない）、
   実際のsudoパスワードが不明な工場出荷時の値のままだったため。→ ユーザーが手動でログイン
   し直し（`cumulus`/`cumulus`でログインすると`administrator enforced`のパスワード変更が
   強制されるため、そこで新パスワードに変更）、以後そのパスワードでsudoが通るようになった。
3. **adapter番号とswpポート番号が1つズレていた** — `topology.yml`で`LEAF1:0/0`をSPINEに、
   `LEAF1:1/0`をPC1に配線していたが、実機の`ip -br link show`のMACアドレス
   （`swp1=...:01`, `eth0=...:00`）から、adapter0は実は`eth0`（mgmt）、adapter1が
   `swp1`であることが判明。SPINEは実際にはLEAF1の`eth0`（mgmt、別VRF）に繋がっており、
   `swp1`（10.255.0.2/30を設定した側）はPC1に繋がっていたため、当然ping不通・OSPF
   ネイバーも上がらなかった。→ GNS3 APIでリンクを一旦削除し、`LEAF1:1/0`(=swp1)を
   SPINEへ、`LEAF1:2/0`(=swp2)をPC1へ、と1つずらして再接続。
4. **OSPFネイバーが`ExStart`で停止** — リンク再配線後、`show ip ospf neighbor`で
   `10.255.255.1  ExStart/Backup`のまま進まなかった。SPINE（eth0, MTU 1500）とLEAF
   （swp1, MTU 9216）のMTU不一致が原因（`show ip ospf interface`の`MTU mismatch
   detection: enabled`表示から推測）。→ 両側インターフェースに`ip ospf mtu-ignore`を
   追加したところ即座に`Full`に遷移。
5. **PC1→PC2 pingが通らない（EVPN Type-3は正常なのにMAC学習が0のまま）** — VTEP間の
   VXLANトンネル自体はEVPNで正しく確立していたが、`bridge fdb show`で該当MACが
   `vlan 1`扱いになっていた。`swp2`側に`bridge-access 10`を付け忘れており、ブリッジの
   デフォルトVLAN（1）のままVNI 10010（VLAN10）に乗っていなかったため。→ `swp2`にも
   `bridge-access 10`を追加して`ifreload`したところ、即座に疎通・MAC学習（2件）とも成功。

## 8. 運用手順

### 8.1 状態確認コマンド

```
# SPINE (vtysh)
show ip ospf neighbor
show bgp l2vpn evpn summary
show bgp l2vpn evpn route

# LEAF1/LEAF2 (sudo vtysh / シェル。NCLUの `net show` は使用可だが `net add` は不可)
sudo vtysh -c "show ip ospf neighbor"
sudo vtysh -c "show bgp l2vpn evpn summary"
sudo vtysh -c "show evpn vni 10010"
sudo vtysh -c "show bgp l2vpn evpn route"
bridge fdb show
ip -br link show      ! adapter番号とswp番号の対応確認（MACの末尾でどのadapterか判別できる）
```

### 8.2 想定される障害切り分け

- **リンクが繋がっているはずなのにpingが通らない**: まず`ip -br link show`でswp1等が
  `LOWER_UP`になっているか確認する。**Cumulus VXはadapter0=eth0(mgmt)、adapter1=swp1、
  adapter2=swp2 ...と1つズレる**ため、GNS3の`links:`で意図した相手と実際に繋がっている
  ポートが食い違っていないか、`ip -br link show`のMACアドレス末尾（adapter番号に対応）で
  必ず実機確認すること。本トポロジーでこの問題が発生し、SPINEがLEAF1のmgmtポートに
  誤配線されていた。
- **OSPFネイバーが`ExStart`のまま進まない**: SPINE(MTU 1500)とLEAF(MTU 9216)のMTU
  不一致が典型的な原因。両側のインターフェースに`ip ospf mtu-ignore`を追加する。
- **OSPFネイバーがそもそも上がらない**: `interface`個別の`ip ospf area`設定だけでなく
  `router ospf`でプロセス自体がインスタンス化されているか（`show ip ospf neighbor`実行前に
  一度`router ospf`と入力しているか）を確認する。またSPINE側`network`文の範囲指定ミス
  （`10.255.0.0/30`と`10.255.0.4/30`を取り違えていないか）も疑う。
- **BGP EVPNセッションが張れない**: `update-source lo`の設定漏れでLoopback以外の
  アドレスからセッションを試みていないか確認する。Underlay（OSPF）が正常でLoopback同士が
  pingできることが前提条件になる。
- **VNI 10010のType-3ルートが対向に見えない**: LEAF側の`advertise-all-vni`の投入漏れ、
  またはSPINE側の`route-reflector-client`設定漏れ（RRクライアント指定がないとSPINEは
  EVPNルートを他のLEAFへ反射しない）を疑う。
- **EVPN Type-3ルートは正常なのにPC1-PC2間でpingが通らない**: `bridge fdb show`で
  お互いのMACアドレスが正しい`vlan`（本設計では`10`）に乗っているか確認する。
  ホスト収容ポート（`swp2`）に`bridge-access 10`を付け忘れ、デフォルトVLAN(1)のままに
  なっているのが典型的な原因（`vni10010`側だけ`bridge access 10`を設定しても不十分）。
- **Cumulus VXで`net add`コマンドが認識されない**: このテンプレートのビルドではNCLUの
  `net add`（interface/loopback/bridge/vxlan/bgp）が使用不可（`net show`/`net help`は可）。
  代替の`nv`（NVUE）もデーモン`nvued`がRAM不足でOOM Killerに落ちる。
  `/etc/network/interfaces`の直接編集 + `ifreload -a`、ルーティングは`vtysh`で行う
  （[6章](#6-コンフィグ抜粋)参照）。
- **sudoのパスワードが分からない**: GNS3公式カタログの`cumulus/cumulus`はログインには
  使えてもsudoには使えないことがある（cloud-init未実行の環境）。`cumulus/cumulus`で
  ログインした際に強制されるパスワード変更で新しいパスワードを設定すれば、以後その
  パスワードでsudoも通るようになる。

---

前段は [基本設計書](./vxlan-evpn-basic-design.md) を参照。
