# 2拠点間 IPsec + GRE(OSPF) 接続ネットワーク 構築手順書

- **対象トポロジー**: [`ipsec_gre_ospf_topology.yml`](../examples/ipsec_gre_ospf_topology.yml)
- **版数**: 1.0
- **関連文書**: [基本設計書](./ipsec-gre-ospf-basic-design.md) / [詳細設計書](./ipsec-gre-ospf-detailed-design.md)

本書は `ipsec_gre_ospf_topology.yml` をGNS3上にデプロイし、IPsec → GRE → OSPF → 拠点間疎通の
順に段階的に動作確認するための実施手順を示す。**本書自体は手順の定義であり、GNS3実機での
実施結果は記録していない**（実施結果は[詳細設計書 6章](./ipsec-gre-ospf-detailed-design.md#6-試験項目計画)の表を参照・更新すること）。

## 目次

1. [前提条件](#1-前提条件)
2. [デプロイ](#2-デプロイ)
3. [IOSvノードへの手動config投入](#3-iosvノードへの手動config投入)
4. [段階的な動作確認](#4-段階的な動作確認)
5. [トラブルシューティング](#5-トラブルシューティング)
6. [後片付け](#6-後片付け)

## 1. 前提条件

- `gns3lab_config.yml` にGNS3サーバーの接続情報が設定済みであること。
- `gns3lab_templates.yml` に以下の役割名が実テンプレート名にマッピング済みであること。

  | 役割名（`template:`） | 想定する実テンプレート |
  |---|---|
  | `iosv-router` | Cisco IOSv 15.9(3)M12（GigabitEthernet、4アダプタ） |
  | `switch` | Ethernet switch |
  | `vpcs` | VPCS |

  未登録の場合は `gns3lab templates` で利用可能なテンプレート名を確認し、
  `gns3lab_templates.yml` に追記する（GUI版なら「テンプレート対応」タブから登録可能）。
- Cisco IOSvイメージがGNS3サーバー側に登録済みであること（GNS3自体はIOSイメージを
  配布していないため、未登録の場合は事前にGNS3 GUIから登録する）。

## 2. デプロイ

```
gns3lab deploy examples/ipsec_gre_ospf_topology.yml
```

- プロジェクト作成 → 全ノード作成 → リンク作成 → 全ノード起動 → `config:` の自動投入、
  まで一括実行される。
- `Host-A` / `Host-B` / `Server-A` / `Server-B`（VPCS）は自動投入対象のため、この時点で
  IPアドレス設定まで完了する。
- `WAN-RT-A` / `WAN-RT-B` / `ACCESS-RT-A` / `ACCESS-RT-B`（IOSv、QEMU系）は自動投入非対応
  のため、各ノードについて `失敗` または投入スキップの表示が出る。これは想定内の挙動であり、
  次の3章で手動投入する。
- 実行後は `gns3lab status ipsec_gre_ospf_lab` で全ノードが `started` になっていることを
  確認する。

## 3. IOSvノードへの手動config投入

IOSvノードはGNS3のWebUIまたはGUIからコンソール（telnet）を開き、`ipsec_gre_ospf_topology.yml`
の該当ノードの `config:` ブロックをそのまま貼り付ける。`gns3lab status ipsec_gre_ospf_lab` で
表示されるコンソールポート（例: `127.0.0.1:5001`）に `telnet` で直接接続してもよい。

投入順序は下記の通り推奨する（コア側から先に確立し、各段階でOSPFネイバー等を確認しながら
進めることで、問題発生時の切り分け範囲を狭められる）。

1. **`WAN-RT-A`** の `config:` を投入する。
2. **`WAN-RT-B`** の `config:` を投入する。
   - この時点で `WAN-RT-A` の `show crypto isakmp sa` / `show crypto ipsec sa` を確認し、
     IPsec SAが確立することを確認してから次へ進む（[4.1](#41-ipsec区間の確認)）。
3. **`ACCESS-RT-A`** の `config:` を投入する。
4. **`ACCESS-RT-B`** の `config:` を投入する。

各ノードのコンソールでの投入手順は以下の共通パターン。

```
enable
configure terminal
（config: の内容をそのまま貼り付け）
end
write memory
```

> IOSvは起動直後、コンソールがプロンプトを受け付けるまで数十秒かかることがある。
> `deploy` 直後にすぐ接続できない場合は少し待ってから再接続する。

## 4. 段階的な動作確認

各レイヤーを積み上げ式に確認する。下位レイヤーが確立していないと上位レイヤーは正常に
動作しないため、必ずこの順序で確認すること。

### 4.1 IPsec区間の確認

`WAN-RT-A` で実行:

```
show crypto isakmp sa
show crypto ipsec sa
```

- ISAKMP SAが `203.0.113.1` ⇔ `203.0.113.2` 間で `QM_IDLE` / `ACTIVE` になっていること。
- ESP SA（inbound/outbound）がTunnel0向けに確立していること。

確立していない場合は3章の投入順序・内容（特に事前共有鍵と対向IP）を見直す。

### 4.2 GRE / OSPFネイバーの確認

`WAN-RT-A` で実行:

```
show interfaces tunnel0
show ip ospf neighbor
```

- `Tunnel0` の line protocol が `up` であること（IPsecが未確立だと `up/down` のままになる）。
- `WAN-RT-B`（router-id `2.2.2.2`）がTunnel0経由でFULLになっていること。

`ACCESS-RT-A` / `ACCESS-RT-B` でも `show ip ospf neighbor` を実行し、それぞれの上流WAN-RTと
Gi0/0経由でFULLになっていることを確認する。

### 4.3 経路の確認（host = O / server = O E2）

`WAN-RT-A` で実行:

```
show ip route
```

- `10.20.2.0/24`（Host-B）が `O`（エリア内経路）で見えること。
- `10.30.2.0/24`（Server-B）が `O E2`（再配布されたstatic経路）で見えること。

`O E2` が見えない場合は、`WAN-RT-B` に `ip route 10.30.2.0 255.255.255.0 10.10.2.2` と
`router ospf 1` 配下の `redistribute static subnets` の両方が投入されているか確認する。

### 4.4 拠点間疎通確認

以下をこの順で実施し、いずれも成功することを確認する。

```
Host-A   -> ping 10.20.2.10   (Host-B、OSPFのO経路)
Host-A   -> ping 10.30.2.10   (Server-B、OSPFのO E2経路)
Server-A -> ping 10.30.2.10   (Server-B、双方ともstatic route再配布経由)
```

## 5. トラブルシューティング

主要な切り分けポイントは[詳細設計書 7.2 想定される障害切り分け](./ipsec-gre-ospf-detailed-design.md#72-想定される障害切り分け)にまとめている。本手順書の各ステップ（4.1〜4.3）を
上から順に確認すれば、どのレイヤーで問題が発生しているかを特定できる。

| 症状 | 主な確認箇所 |
|---|---|
| IPsec SAが確立しない | 4.1（事前共有鍵・対向IPの一致） |
| Tunnel0がup/downのまま | 4.1が正常か再確認（IPsec未確立だとGREも疎通しない） |
| OSPFネイバーがFULLにならない | 4.2（Tunnel0のIPアドレス・`network`文のワイルドカードマスク） |
| Server宛の経路が見えない | 4.3（`ip route` と `redistribute static subnets` の両方） |
| Host宛の経路が見えない | ACCESS-RTのOSPF `network`文にHostセグメントが含まれているか |

## 6. 後片付け

検証が完了したらプロジェクトを削除する。

```
gns3lab destroy examples/ipsec_gre_ospf_topology.yml
```

（`ipsec_gre_ospf_topology.yml` 内の `name: ipsec_gre_ospf_lab` を自動で読み取り、該当
プロジェクトの全ノードを停止した上で削除する）

---

前段は [詳細設計書](./ipsec-gre-ospf-detailed-design.md) を参照。
