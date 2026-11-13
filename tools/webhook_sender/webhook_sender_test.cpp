// Synthetic qualification adapter. No API credentials, Telegram client or HTTP sender stub.
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

namespace {
struct Result {
  std::atomic<bool> done{false};
  std::atomic<bool> acknowledged{false};
};

class Probe final : public telegram_bot_api::WebhookActor::Callback {
 public:
  Probe(int port, td::string nonce, std::shared_ptr<Result> result)
      : port_(port), nonce_(std::move(nonce)), result_(std::move(result)) {}

 private:
  int port_;
  td::string nonce_;
  std::shared_ptr<Result> result_;
  std::shared_ptr<telegram_bot_api::ClientParameters> parameters_;
  td::ActorOwn<telegram_bot_api::WebhookActor> sender_;

  void start_up() final {
    parameters_ = std::make_shared<telegram_bot_api::ClientParameters>();
    parameters_->local_mode_ = true;
    parameters_->shared_data_ = std::make_shared<telegram_bot_api::SharedData>();
    auto &shared = *parameters_->shared_data_;
    shared.unix_time_difference_ = static_cast<double>(std::time(nullptr)) - td::Time::now();
    shared.tqueue_ = td::TQueue::create();
    shared.tqueue_->set_callback(td::make_unique<td::TQueueMemoryStorage>());
    auto event = shared.tqueue_->push(1, "\"message\":{\"message_id\":1,\"text\":\"release-probe-" + nonce_ + "\"}",
                                     static_cast<td::int32>(std::time(nullptr) + 60), 0, {});
    event.ensure();
    auto url = td::parse_url("http://127.0.0.1:" + std::to_string(port_) + "/release-probe").move_as_ok();
    sender_ = td::create_actor<telegram_bot_api::WebhookActor>(
        "ReleaseProductionSender", td::ActorShared<telegram_bot_api::WebhookActor::Callback>(td::actor_id(this), 0),
        1, std::move(url), td::string(), 1, false, td::string("127.0.0.1"), true, td::string(), parameters_);
    set_timeout_in(0.05);
  }
  void timeout_expired() final {
    // Poll on the same scheduler as TQueue; callback timing is not delivery proof.
    webhook_success();
    if (!result_->done.load()) set_timeout_in(0.05);
  }
  void webhook_verified(td::string) final {}
  void webhook_success() final {
    // Upstream also reports success while loading a queue: that is not an ACK.
    if (parameters_->shared_data_->tqueue_->get_size(1) == 0) {
      result_->acknowledged.store(true);
      result_->done.store(true);
      td::send_closure(sender_.get(), &telegram_bot_api::WebhookActor::close);
    }
  }
  void webhook_error(td::Status) final { result_->done.store(true); }
  void webhook_closed(td::Status) final { result_->done.store(true); stop(); }
  void send(telegram_bot_api::PromisedQueryPtr) final { result_->done.store(true); }
};
}  // namespace

int main(int argc, char **argv) {
  if (argc != 3) return 2;
  td::string nonce(argv[2]);
  if (nonce.size() != 32 || nonce.find_first_not_of("0123456789abcdef") != td::string::npos) return 2;
  char *end = nullptr;
  auto port = std::strtol(argv[1], &end, 10);
  if (*end || port < 1 || port > 65535) return 2;
  auto result = std::make_shared<Result>();
  td::ConcurrentScheduler scheduler(telegram_bot_api::SharedData::get_thread_count() - 1);
  scheduler.create_actor_unsafe<Probe>(telegram_bot_api::SharedData::get_client_scheduler_id(),
                                      "ReleaseProbe", static_cast<int>(port), nonce, result).release();
  scheduler.start();
  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
  while (!result->done.load() && std::chrono::steady_clock::now() < deadline) scheduler.run_main(0.05);
  scheduler.finish();
  if (!result->acknowledged.load()) return 1;
  std::cout << "{\"queue_acknowledged\":true}\n";
  return 0;
}
