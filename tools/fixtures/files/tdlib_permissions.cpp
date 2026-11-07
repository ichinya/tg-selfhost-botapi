// Offline probe linked to the exact pinned TDLib tdutils target.
// Covers FileLoaderUtils' 0640 create + 0750 mkdir + rename contract; no Telegram.
#include "td/utils/port/FileFd.h"
#include "td/utils/port/path.h"
#include <sys/stat.h>
#include <unistd.h>
#include <iostream>
#include <string>

int main() {
  if (getuid() != 101 || getgid() != 101) return 1;
  umask(0007);
  for (const auto *suffix : {"12345:SYNTHETIC_A", "12345:SYNTHETIC_B"}) {
    std::string root = std::string("/var/lib/telegram-bot-api-files/") + suffix;
    auto temp = root + "/tdlib-temp";
    auto docs = root + "/tdlib-documents";
    if (td::mkdir(temp, 0750).is_error() || td::mkdir(docs, 0750).is_error()) return 1;
    auto staging = temp + "/fixture.bin";
    auto destination = docs + "/fixture.bin";
    auto created = td::FileFd::open(staging, td::FileFd::Read | td::FileFd::Write | td::FileFd::CreateNew, 0640);
    if (created.is_error()) return 1;
    auto fd = created.move_as_ok();
    auto written = fd.write("EXACT_SYNTHETIC_BYTES");
    if (written.is_error() || written.ok() != 21) return 1;
    fd.close();
    // FileLoaderUtils first reserves a destination and then renames the temp FD's file.
    auto reserved = td::FileFd::open(destination, td::FileFd::Read | td::FileFd::Write | td::FileFd::CreateNew, 0640);
    if (reserved.is_error()) return 1;
    reserved.move_as_ok().close();
    if (td::rename(staging, destination).is_error()) return 1;
    struct stat file{}, directory{};
    if (::stat(destination.c_str(), &file) || ::stat(docs.c_str(), &directory)) return 1;
    if ((file.st_mode & 07777) != 0640 || file.st_uid != 101 || file.st_gid != 101 || file.st_nlink != 1) return 1;
    if ((directory.st_mode & 07777) != 02750 || directory.st_uid != 101 || directory.st_gid != 101) return 1;
  }
  std::cout << "{\"tdlib_create_move\":\"PASS\",\"file_mode\":\"0640\",\"directory_mode\":\"2750\"}\n";
  return 0;
}
