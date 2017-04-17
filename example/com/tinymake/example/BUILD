java_binary(
  name = "example",
  srcs = ["HelloWorld.java"],
  main_class = "com.tinymake.example.HelloWorld",
  deps = ["//example/com/tinymake/examplelib"],
  runtime_deps = [":example_lib"],
)

java_library(
  name = "example_lib",
  srcs = ["Example.java"],
)
