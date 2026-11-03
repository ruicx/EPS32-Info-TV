#include "application.h"

/** Start the application with explicit process-lifetime ownership. */
extern "C" void app_main() {
  static info_tv::Application application;
  application.start();
}
