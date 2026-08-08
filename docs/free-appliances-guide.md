# 無料ルータ/スイッチOS 導入済みアプライアンス ガイド

このGNS3環境（`vm` compute）に導入済みの無料ルータ/スイッチOSについて、それぞれの特徴・用途・ログイン情報・基本操作をまとめる。いずれも `gns3lab_templates.yml` に役割名で登録済みで、`topology.yml` の `template:` にその役割名を書くだけで配置できる。

## 目次

1. [一覧](#1-一覧)
2. [SONiC-VS](#2-sonic-vs)
3. [FRR](#3-frr)
4. [Cumulus VX](#4-cumulus-vx)
5. [OPNsense](#5-opnsense)
6. [MikroTik CHR](#6-mikrotik-chr)
7. [OpenWrt](#7-openwrt)
8. [config: 自動投入の対応状況](#8-config-自動投入の対応状況)

## 1. 一覧

| 役割名 (`template:`) | 実体 | 分類 | デフォルトログイン | RAM/vCPU | ポート数 |
|---|---|---|---|---|---|
| `sonic-switch` | SONiC-VS | データセンタースイッチ | `admin` / `YourPaSsWoRd` | 4096MB / 2 | 9 (eth0=mgmt + 8) |
| `frr-router` | FRR 8.2.2 | ルーティングスタック専用 | `root` / `root` | 256MB / 1 | 8 |
| `cumulus-switch` | Cumulus VX 5.4.0 | データセンタースイッチ | `cumulus` / `cumulus` | 1024MB / 1 | 7 (swp1-7) |
| `opnsense-firewall` | OPNsense 26.1 | ファイアウォール/ルータ | `root` / `opnsense` | 1024MB / 1 | 4 (em0-3) |
| `mikrotik-chr` | MikroTik CHR 7.22.1 | ルータ (RouterOS) | `admin` / (空) | 384MB / 1 | 8 (ether1-8) |
| `openwrt-router` | OpenWrt 25.12.0 | ルータ (SOHO) | `root` / (未設定、要`passwd`) | 128MB / 1 | 4 |

全機種ともQEMU上で動作し、`vm` compute（GNS3 VM, KVM）に配置している。GNS3のコンソール（telnet）から直接ログイン・操作する。

## 2. SONiC-VS

### 特徴
- Microsoft/Linux Foundation発、ホワイトボックススイッチ向けNOS。実運用でも大手データセンター事業者に採用されている。
- `swss` / `syncd` / `bgp` / `teamd` / `lldp` など機能ごとに分離されたdockerコンテナ群で構成される（本物のSONiCと同じアーキテクチャ）。
- SAI (Switch Abstraction Interface) 経由でASICを抽象化する設計だが、VS(Virtual Switch)ビルドはASICを持たないためソフトウェアスイッチとして動作する。
- 設定はSONiC独自の `config`/`show` CLI（config_db）と、BGP/OSPF等ルーティング専用の `vtysh`(FRR統合)の二階建て。

### 用途
- ホワイトボックス/SONiC運用の学習
- BGP EVPN・VXLANなどデータセンターファブリックの検証
- 実務でSONiCを扱う前の操作習熟

### 基本操作（ログイン後）
```
admin@sonic:~$ show interfaces status
admin@sonic:~$ sudo config interface ip add Ethernet0 10.0.0.1/24
admin@sonic:~$ sudo config interface startup Ethernet0
admin@sonic:~$ vtysh
sonic# configure terminal
sonic(config)# router bgp 65000
sonic(config-router)# neighbor 10.0.0.2 remote-as 65001
sonic(config-router)# end
sonic# write memory
sonic# exit
admin@sonic:~$ sudo config save -y   # config_db側の設定を永続化
```

### 注意点
- 起動に数分かかる（複数dockerコンテナが立ち上がるため）。`sonic login:` が出るまで待つこと。
- `config:` によるCLI自動投入は `platform: sonic` を指定した場合のみ対応（[README](../README.md#sonic-vsへの自動投入platform-sonic)参照）。ただし対応範囲は **vtysh(FRR)が扱うルーティング設定のみ**。インターフェースIPやVLANなど `config_db` 側の設定は自動投入対象外。

## 3. FRR

### 特徴
- FRRouting (FRR)。Quaggaの後継となるOSSルーティングスタックで、BGP/OSPF/OSPFv3/IS-IS/LDP/PIM/RIPなど主要プロトコルを実装。
- 特定ベンダーのシリコンに依存しない純粋なソフトウェアルータ。カーネルのルーティングテーブルとネイティブに統合される（設定した経路がそのままLinux kernelのFIBに反映される）ため、動作がシンプルで理解しやすい。
- SONiC/Cumulus VXの内部でもルーティングエンジンとしてFRRが使われており、`vtysh`の操作感はどちらも共通。

### 用途
- マルチベンダー環境の相互接続検証（BGP/OSPF）
- ルーティングプロトコルそのものの挙動比較・学習用の軽量ルータ
- SONiC/Cumulusの `vtysh` 操作を先に練習する

### 基本操作（ログイン後）
```
# vtysh
Router# configure terminal
Router(config)# router ospf
Router(config-router)# network 10.0.0.0/24 area 0
Router(config-router)# end
Router# write memory
Router# show ip ospf neighbor
```
ログインシェルから抜けてしまった場合は `vtysh` と打てば戻れる。

### 注意点
- ルーティングデーモンのみのため、インターフェースIPなど基本的なLinuxネットワーク設定は `ip addr` 等、通常のLinuxコマンドで行う。
- `config:` 自動投入は現状 gns3lab 未対応（GNS3コンソールから手動投入）。ロジック自体はSONiCの `_push_sonic_vtysh_config` を流用できるため、対応させる場合は拡張が必要。

## 4. Cumulus VX

### 特徴
- 現NVIDIA傘下のCumulus Networksが提供する、Linuxベースのデータセンタースイッチ OS。実機Cumulus Linuxと基本同じソフトウェアスタックをASIC非搭載でエミュレーションしたもの。
- 設定方法が2系統ある: NCLU（`net` コマンド、Cisco風の使い勝手）と `vtysh`（FRR統合、BGP/OSPF等ルーティング専用）。
- VXLAN/EVPN/MLAG（マルチシャーシLAG）などデータセンターファブリックの主要機能をサポート。SONiCと並んでホワイトボックスNOSの代表格。

### 用途
- スパイン・リーフ構成、EVPN-VXLANファブリックの設計検証
- SONiCとの設定方法・思想の比較学習

### 基本操作（ログイン後）
```
cumulus@cumulus:~$ net show interface
```
`net show`/`net help`は動くが、下記の注意点の通り**`net add`（NCLU書き込み系）はこの
GNS3テンプレートでは使用不可**。実機で確認できた代替手順は
[vxlan-evpn-detailed-design.md 6章](./vxlan-evpn-detailed-design.md#6-コンフィグ抜粋)を参照。
概要は以下の通り。

```
# L2/L3設定は ifupdown2 (/etc/network/interfaces) を直接編集
sudo tee -a /etc/network/interfaces << 'EOF'
auto swp1
iface swp1
    address 10.0.0.1/24
EOF
sudo ifreload -a

# ルーティングは vtysh (FRRデーモンの有効化が別途必要、後述)
sudo vtysh -c "configure terminal" -c "router bgp 65000" -c "neighbor swp1 remote-as external"
```

### 注意点（実機検証で判明）
- **`net add interface/loopback/bridge/vxlan/bgp`はこのテンプレートでは動作しない**
  （`ERROR: Command not found`）。`dpkg -L nclu`で確認したところ、このビルドのNCLU
  プラグインはdns/dhcp/nat/ntp/ports/snmp等に限られ、L2/L3コア機能が含まれていない。
  代替の`nv`（NVUE）もデーモン`nvued`がテンプレート既定RAM（1024MB、実効723MB）では
  OOM Killerに落とされて起動しない。→ 上記の通りifupdown2 + vtysh直接方式を使うこと。
- `/etc/frr/daemons`はデフォルトで`bgpd=no`/`ospfd=no`。`sed`等で`yes`に変更して
  `systemctl restart frr`が必要（vtyshで`router bgp`等を入力しても`bgpd is not
  running`と出るだけで無反応な場合、まずここを疑う）。
- ブリッジポートには`bridge-access <vlan>`を明示しないとデフォルトVLAN(1)のままになる
  （VXLANインターフェース側だけでなく、ホスト収容ポート側にも必要）。
- **GNS3のadapter番号とswpポート番号が1つズレる**（`adapter0`=`eth0`(mgmt)、`adapter1`=
  `swp1`、`adapter2`=`swp2`...）。トポロジーYAMLの`links:`でハマりやすいので、
  `ip -br link show`のMACアドレス末尾で実際の対応を確認すること。
- 初回ログイン（`cumulus`/`cumulus`）はパスワード変更が強制される。GNS3公式カタログの
  `cumulus/cumulus`はログインには使えてもsudoパスワードとしては通らないことがある
  （cloud-init未実行の環境のため）。ログイン時の強制パスワード変更で新パスワードを
  設定すれば、以後sudoにもそのパスワードが使える。
- `config:` 自動投入は現状 gns3lab 未対応。

## 5. OPNsense

### 特徴
- FreeBSDベースの高機能OSSファイアウォール/ルータ。pfSenseからのフォーク。
- 運用はWeb GUI（HTTPS管理画面）が中心。ファイアウォールルール、NAT、VPN（IPsec/WireGuard/OpenVPN）、IDS/IPS（Suricata）などをGUIから設定する思想で、CLIでの細かい設定投入には不向き。
- プラグインエコシステムが豊富（HAProxy、ntopng等）。

### 用途
- 本格的なステートフルファイアウォール・VPNゲートウェイの検証
- pfSense/OPNsense系アプライアンスの操作学習

### 基本操作
- コンソール起動後、番号選択式のメニュー（インターフェース再割当、IPアドレス変更、リブート等）が表示される。
- ネットワーク設定変更後は、ブラウザで `https://192.168.1.1`（デフォルトLAN IP、`em1`）にアクセスしてWeb GUIから本格的な設定を行う。

### 注意点
- nano版イメージのためインストール手順は不要（起動すればすぐ使える）。
- `config:` 自動投入は現状 gns3lab 未対応。GUI中心のOSのためCLI経由の自動化とは相性が悪い。

## 6. MikroTik CHR

### 特徴
- MikroTikのクラウド/仮想化向けルータOS（RouterOS）。独自のRouterOS CLIと、Winbox（Windows/Linux用GUIツール）の両方で操作できる。
- NAT、VPN（IPsec/WireGuard/L2TP等）、QoS、BGP/OSPF、MPLS/VPLS、ファイアウォールなど非常に多機能。
- 無料ライセンス（Free/Trial）は帯域制限（合計1Mbps程度）があるが、機能自体はほぼフルセットで使える。ラボ検証用途なら問題ない。

### 用途
- SOHO/ISPルータ運用の模擬
- RouterOS特有のCLI・機能（MPLS/VPLS等）の検証
- MikroTik実機の操作を導入前に習熟する

### 基本操作（ログイン後）
```
[admin@MikroTik] > /ip address add address=10.0.0.1/24 interface=ether1
[admin@MikroTik] > /ip route add gateway=10.0.0.254
[admin@MikroTik] > /ip firewall nat add chain=srcnat action=masquerade out-interface=ether1
[admin@MikroTik] > /export                      # 現在の設定を確認
```

### 注意点
- 初回起動時にRouterOS本体がディスクへ自動インストールされる（数十秒〜数分、自動的に再起動が入る）。1回目の起動ログだけでは操作可能にならないので焦らないこと。
- `config:` 自動投入は現状 gns3lab 未対応。

## 7. OpenWrt

### 特徴
- 組込み/家庭用ルータ向けの軽量Linuxディストリビューション。実際の市販ルータ（多くのメーカー製品）にそのまま書き込んで使われている実績のあるOS。
- UCI (Unified Configuration Interface) による一元的な設定管理が特徴。`/etc/config/` 以下のテキストファイルを直接編集するか、`uci` コマンドで操作する。
- `opkg` パッケージ管理で、WireGuard・AdGuard Home・追加のWiFiドライバなど機能を後から追加できる。

### 用途
- 家庭用/SOHOルータのNAT・ファイアウォール構成の学習
- Linuxのネットワークスタック（`iptables`/`nftables`、`tc` によるQoS）の基礎学習

### 基本操作（ログイン後）
```
root@OpenWrt:~# passwd                              # 初回はパスワード未設定なので設定推奨
root@OpenWrt:~# uci show network
root@OpenWrt:~# uci set network.lan.ipaddr='192.168.1.1'
root@OpenWrt:~# uci commit network
root@OpenWrt:~# /etc/init.d/network restart
```
`Ethernet0` がLAN、`Ethernet1` がWAN、`Ethernet2`/`Ethernet3` は予備。

### 注意点
- `config:` 自動投入は現状 gns3lab 未対応。

## 8. config: 自動投入の対応状況

`gns3lab deploy`/`configure` の `config:` によるCLI自動投入（[README](../README.md#2b-ノードに初期設定を持たせるconfig自動投入)参照）は、機種ごとに対応状況が異なる。

| 機種 | 対応方式 | 備考 |
|---|---|---|
| dynamips/IOU (`ios-router`等) | `enable`→`configure terminal` | フル対応 |
| VPCS | プロンプト待ちで行投入 | フル対応 |
| SONiC-VS (`platform: sonic`指定時) | ログイン→`vtysh`→`configure terminal` | vtysh(FRR)が扱うルーティング設定のみ |
| FRR / Cumulus VX / OPNsense / MikroTik CHR / OpenWrt | — | **未対応**。GNS3コンソールから手動投入 |

FRRとCumulus VXは、SONiC向けに実装した `_push_sonic_vtysh_config`（[console.py](../src/gns3lab/console.py)）とほぼ同じ「ログイン→vtysh→configure terminal」の流れが使えるため、対応を追加するのは比較的容易。OPNsense/MikroTik CHR/OpenWrtはCLI体系が大きく異なるため、それぞれ専用のログイン・投入ロジックが必要になる。
