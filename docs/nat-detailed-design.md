# NAT (PAT/静的NAT) 検証ネットワーク 詳細設計書

- **対象トポロジー**: [`nat_topology.yml`](../examples/nat_topology.yml)
- **版数**: 1.0
- **前提**: [基本設計書](./nat-basic-design.md) で定めた方針を、実際のIPアドレス・インターフェース・NATパラメータ・コンフィグまで落とし込む。試験項目は現時点で**未実施**（下記6章参照）。

## 目次

1. [IPアドレス設計](#1-ipアドレス設計)
2. [インターフェース設計](#2-インターフェース設計)
3. [NAT変換設計](#3-nat変換設計)
4. [コンフィグ抜粋](#4-コンフィグ抜粋)
5. [試験項目・結果](#5-試験項目結果)
6. [運用手順](#6-運用手順)

## 1. IPアドレス設計

| セグメント | ネットワーク | 用途 | 主要IP |
|---|---|---|---|
| inside（内部LAN） | `192.168.1.0/24` | 内部クライアント・サーバーセグメント | `R1 Gi0/0=.1`, `PC1=.10`, `PC2=.11`, `SVR1=.100` |
| outside（外部） | `203.0.113.0/24`（RFC5737検証用） | 外部ホスト・R1 outside側 | `R1 Gi0/1=.1`, `EXT-PC=.10` |
| 静的NAT公開アドレス | `203.0.113.100` | SVR1のグローバル代表アドレス | `192.168.1.100` と1:1固定変換 |
| PAT共有アドレス | `203.0.113.1`（R1 Gi0/1と共用） | PC1/PC2のoverload変換先 | ポート番号で複数セッションを多重化 |

## 2. インターフェース設計

| 機器 | インターフェース | IPアドレス | 用途 |
|---|---|---|---|
| `R1` | `Gi0/0` | `192.168.1.1/24` | inside（`ip nat inside`） |
| `R1` | `Gi0/1` | `203.0.113.1/24` | outside（`ip nat outside`） |
| `PC1` | (VPCS) | `192.168.1.10/24` | gateway = R1 Gi0/0 |
| `PC2` | (VPCS) | `192.168.1.11/24` | gateway = R1 Gi0/0 |
| `SVR1` | (VPCS) | `192.168.1.100/24` | gateway = R1 Gi0/0、静的NAT対象 |
| `EXT-PC` | (VPCS) | `203.0.113.10/24` | gateway = R1 Gi0/1（同一セグメント） |

## 3. NAT変換設計

### 3.1 ACL（overload対象定義）

```
access-list 1 permit 192.168.1.0 0.0.0.255
```

内部セグメント全体を動的PATの対象として定義する。実際に動的PATが適用されるのはSVR1を除くPC1/PC2のみ（[基本設計書 4.1](./nat-basic-design.md#41-優先順位)参照）。

### 3.2 動的PAT（overload）

```
ip nat inside source list 1 interface GigabitEthernet0/1 overload
```

| 項目 | 設定値 |
|---|---|
| 変換方式 | PAT（Port Address Translation、overload） |
| 対象内部アドレス | ACL 1（`192.168.1.0/24`） |
| 変換先 | outside インターフェース（Gi0/1）のアドレス `203.0.113.1` |
| 多重化単位 | 送信元ポート番号（複数内部ホストが同一外部IPを共有） |

### 3.3 静的NAT

```
ip nat inside source static 192.168.1.100 203.0.113.100
```

| 項目 | 設定値 |
|---|---|
| 変換方式 | 静的NAT（1:1固定） |
| 内部アドレス | `192.168.1.100`（SVR1） |
| 外部アドレス | `203.0.113.100` |
| エントリの性質 | 常時存在（`show ip nat translations` で `---` 表記、通信の有無に関わらず維持される） |

## 4. コンフィグ抜粋

R1の実投入コンフィグ全文。

```
hostname R1
interface GigabitEthernet0/0
 ip address 192.168.1.1 255.255.255.0
 ip nat inside
 no shutdown
interface GigabitEthernet0/1
 ip address 203.0.113.1 255.255.255.0
 ip nat outside
 no shutdown
access-list 1 permit 192.168.1.0 0.0.0.255
ip nat inside source list 1 interface GigabitEthernet0/1 overload
ip nat inside source static 192.168.1.100 203.0.113.100
```

全文は [`nat_topology.yml`](../examples/nat_topology.yml) のR1の `config:` を参照。R1はQEMU系ノード（Cisco IOSv）のため `gns3lab deploy` のCLI自動投入は非対応。GNS3コンソールから上記を手動投入する。

## 5. 試験項目・結果

> **一部実施**: GNS3実機（nat_lab、R1=Cisco IOSv）にて静的NAT関連の試験（No.4〜7）を実施済み。
> 動的PAT関連の試験（No.1〜3、PC1/PC2からの発信）は本書時点では未実施。

| No | 試験項目 | 期待結果 | 実施結果 | 判定 |
|---|---|---|---|---|
| 1 | PC1 → `ping 203.0.113.10`（EXT-PC） | 成功 | 未実施 | ⬜ 未実施 |
| 2 | PC2 → `ping 203.0.113.10`（EXT-PC） | 成功 | 未実施 | ⬜ 未実施 |
| 3 | R1 `show ip nat translations`（試験1・2の後） | PC1/PC2とも `203.0.113.1` を共有し、ポート番号のみ異なる動的エントリが存在 | 未実施 | ⬜ 未実施 |
| 4 | EXT-PC → `ping 203.0.113.100`（SVR1の静的NATアドレス） | 成功 | 5/5成功（1.3〜3.0ms） | ✅ 合格 |
| 5 | R1 `show ip nat translations`（静的エントリ確認） | `192.168.1.100 <-> 203.0.113.100` が `---`（常時）表記で存在 | `--- 203.0.113.100 192.168.1.100 --- ---` を確認。加えて試験4のICMPセッションによる動的エントリ（inside global側も静的アドレス203.0.113.100のまま、203.0.113.1のPATプールとは別扱い）も生成されることを確認 | ✅ 合格 |
| 6 | EXT-PC → `ping 192.168.1.10`（PC1の内部アドレスに直接） | 失敗（対応する変換エントリなし） | 5/5 timeout | ✅ 合格 |
| 7 | R1 `show ip nat statistics` | Total active translations / Hits / Misses が試験内容と整合 | `Total active translations: 11 (1 static, 10 dynamic; 10 extended)` / `Hits: 45  Misses: 0` | ✅ 合格 |

**サマリ（静的NAT関連のみ）**

| 指標 | 結果 |
|---|---|
| 試験項目 合格（No.4〜7） | **4 / 4** |
| 静的NATエントリ | 常時存在（`---`表記）、SVR1(192.168.1.100)⇔203.0.113.100 |
| 内部プライベートアドレスへの直接到達 | 不可（設計通り） |

## 6. 運用手順

### 6.1 NAT状態の確認

```
show ip nat translations     ! 現在の変換エントリ一覧（動的/静的）
show ip nat statistics       ! 変換のヒット数・アクティブ数のサマリ
```

### 6.2 想定される運用シナリオ

- **動的PATエントリが増えすぎた場合**: `clear ip nat translation *` で全エントリをクリアできる（静的エントリは自動的に再生成される）。
- **SVR1への到達性がない場合**: `show ip nat translations` に静的エントリが存在するか確認し、無ければ `ip nat inside source static` の再投入、`ip nat inside`/`ip nat outside` の設定漏れがないか各インターフェースを確認する。
- **動的PATが期待通り動作しない場合**: ACL 1の対象範囲（`192.168.1.0/24`）と、`ip nat inside source list 1 interface GigabitEthernet0/1 overload` のインターフェース指定が実際のoutsideインターフェース（Gi0/1）と一致しているか確認する。

---

前段は [基本設計書](./nat-basic-design.md) を参照。
