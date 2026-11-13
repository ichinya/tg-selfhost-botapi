// Queue a synthetic update through the production WebhookActor. No Telegram client.
#include "telegram-bot-api/ClientParameters.h"
#include "telegram-bot-api/WebhookActor.h"
#include "td/actor/ConcurrentScheduler.h"
#include "td/utils/HttpUrl.h"
#include "td/utils/Time.h"
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <ctime>
#include <iostream>
#include <memory>

struct Outcome {
  std::atomic<bool> acknowledged{false};
  std::atomic<bool> failed{false};
};

class QueueProbe final : public telegram_bot_api::WebhookActor::Callback {
 public:
  QueueProbe(int port, td::string nonce, std::shared_ptr<Outcome> outcome)
      : port_(port), nonce_(std::move(nonce)), outcome_(std::move(outcome)) {}
 private:
  int port_;
  td::string nonce_;
  std::shared_ptr<Outcome> outcome_;
  std::shared_ptr<telegram_bot_api::ClientParameters> parameters_;
  td::ActorOwn<telegram_bot_api::WebhookActor> sender_;
  void start_up() final {
    parameters_ = std::make_shared<telegram_bot_api::ClientParameters>();
    parameters_->local_mode_ = true;
    parameters_->shared_data_ = std::make_shared<telegram_bot_api::SharedData>();
    auto &state = *parameters_->shared_data_;
    state.unix_time_difference_ = static_cast<double>(std::time(nullptr)) - td::Time::now();
    state.tqueue_ = td::TQueue::create();
    state.tqueue_->set_callback(td::make_unique<td::TQueueMemoryStorage>());
    state.tqueue_->push(1, "\"message\":{\"text\":\"" + nonce_ + "\"}",
                       static_cast<td::int32>(std::time(nullptr) + 60), 0, {}).ensure();
    auto url = td::parse_url("http://127.0.0.1:" + std::to_string(port_) + "/probe").move_as_ok();
    sender_ = td::create_actor<telegram_bot_api::WebhookActor>(
        "ProductionWebhookProbe", td::ActorShared<telegram_bot_api::WebhookActor::Callback>(actor_id(this), 0),
        1, std::move(url), td::string(), 1, false, td::string("127.0.0.1"), true, td::string(), parameters_);
    set_timeout_in(0.05);
  }
  void timeout_expired() final {
    if (parameters_->shared_data_->tqueue_->get_size(1) == 0) {
      outcome_->acknowledged.store(true);
      td::send_closure(sender_.get(), &telegram_bot_api::WebhookActor::close);
    } else {
      set_timeout_in(0.05);
    }
  }
  void webhook_verified(td::string) final {}
  void webhook_success() final {} // Queue removal, not this callback, proves ACK.
  void webhook_error(td::Status) final { outcome_->failed.store(true); }
  void webhook_closed(td::Status) final { stop(); }
  void send(telegram_bot_api::PromisedQueryPtr) final { outcome_->failed.store(true); }
};

int main(int argc, char **argv) {
  if (argc != 3) return 2;
  td::string nonce(argv[2]);
  if (nonce.size() != 32 || nonce.find_first_not_of("0123456789abcdef") != td::string::npos) return 2;
  char *end = nullptr;
  auto port = std::strtol(argv[1], &end, 10);
  if (*end || port < 1 || port > 65535) return 2;
  auto outcome = std::make_shared<Outcome>();
  td::ConcurrentScheduler scheduler(telegram_bot_api::SharedData::get_thread_count() - 1);
  scheduler.create_actor_unsafe<QueueProbe>(telegram_bot_api::SharedData::get_client_scheduler_id(),
                                          "QueueProbe", static_cast<int>(port), nonce, outcome).release();
  scheduler.start();
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(8);
  while (!outcome->acknowledged.load() && !outcome->failed.load() && std::chrono::steady_clock::now() < deadline)
    scheduler.run_main(0.05);
  scheduler.finish();
  if (!outcome->acknowledged.load()) return 1;
  std::cout << "{\"queue_acknowledged\":true}\n";
  return 0;
}
