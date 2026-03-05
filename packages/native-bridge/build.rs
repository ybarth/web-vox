fn main() {
    cc::Build::new()
        .file("vendor/sonic/sonic.c")
        .include("vendor/sonic")
        .opt_level(3)
        .compile("sonic");
}
