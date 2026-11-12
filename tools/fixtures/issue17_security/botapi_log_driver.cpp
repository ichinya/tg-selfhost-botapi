// Synthetic driver linked to the patched candidate Query and TDLib HTTP code.
#include "telegram-bot-api/PrivacyLog.h"
#include "telegram-bot-api/Query.h"
#include "td/net/HttpHeaderCreator.h"
#include "td/utils/MemoryLog.h"
#include "td/utils/StringBuilder.h"
#include <iostream>
#include <string>

class Capture final : public td::LogInterface {
 public:
  std::string text;
  void do_append(int, td::CSlice value) final { text += value.str(); }
};
int main() {
  Capture capture;
  telegram_bot_api::PrivacyLog safe(&capture);
  td::MemoryLog<4096> memory;
  telegram_bot_api::PrivacyLog safe_memory(&memory);
  const std::string marker="synthetic_issue17_private_marker";
  for (int level=0;level<=3;level++) {
    safe.do_append(level,marker);
    safe_memory.do_append(level,marker);
  }
  td::string token="123:"+marker, method="untrusted_"+marker, key="secret_token", value=marker;
  td::vector<std::pair<td::MutableSlice,td::MutableSlice>> args{{td::MutableSlice(key),td::MutableSlice(value)}};
  telegram_bot_api::Query query({},token,false,td::MutableSlice(method),std::move(args),{},{},nullptr,td::IPAddress());
  td::StringBuilder builder;
  builder << query;
  if (builder.as_cslice().str().find(marker)!=std::string::npos) return 1;
  if (builder.as_cslice().str().find("args=1")==std::string::npos) return 2;
  td::HttpHeaderCreator header;
  header.init_post("/"+marker);
  header.add_header("Host","example.invalid");
  header.set_content_size(0);
  header.add_header("X-Telegram-Bot-Api-Secret-Token",marker);
  auto bytes=header.finish();
  if (bytes.is_error() || bytes.ok().str().find(marker)==std::string::npos) return 3;
  safe.do_append(3,bytes.ok().str());
  if (capture.text.find(marker)!=std::string::npos || memory.get_buffer().str().find(marker)!=std::string::npos) return 4;
  if (capture.text.find("botapi_event")==std::string::npos) return 5;
  std::cout << "privacy_driver_pass query=1 header=1 sinks=2 levels=4\n";
}
