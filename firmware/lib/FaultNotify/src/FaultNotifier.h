#pragma once
// 障害通知の送り先を表す最小インターフェース。AC入力断(→ AcInputMonitor)を最初の
// 利用者として作るが、送り先(LED・将来のブザー等)ごとの実装差を呼び出し側から
// 隠すためだけの薄い抽象で、AC入力断専用ではない。
//
// **Slack等の外部通知はここに実装しない。** このプロジェクトは`kGfrqFlagPowerFail`
// (→ docs/wire-format.md)でバッチへ正直に申告し、クラウド側の将来のwatchdog Lambda
// (フェーズ9、まだ存在しない)がingest済みデータや生存台帳を見て通知する設計を採る
// ——地震計(NamazuHaUrokoGaNai)の生存台帳+watchdog LambdaがSlack通知する構成と
// 同じ役割分担にするため(→ docs/log/2026-08-15-ac-input-disconnect-detection-impl.md)。
// firmwareが直接HTTP POSTで外部サービスを叩く経路は意図的に避けている
// (device側の実装がクラウド側の通知ロジックと二重化するのを防ぐ)。
// **このインターフェースが担うのはローカルな通知(LED等)だけ。**
//
// 実装(GPIO制御等)はハードウェア依存なのでmain.cpp側に置く。ここは純粋仮想関数
// だけでロジックを持たないので、Arduinoに依存せずtestも要らない
// (他のlibのtest/run.shパターンはロジックが無いここには適用しない)。

namespace fault {

class FaultNotifier {
 public:
  virtual ~FaultNotifier() = default;

  // faulted: true=障害が確定した瞬間、false=復帰した瞬間。
  // 呼ばれるのは呼び出し側(AcInputMonitor::update()の戻り値)が状態変化を検出した
  // 時だけ——毎windowごとの連呼ではない。
  virtual void notify(bool faulted) = 0;
};

}  // namespace fault
