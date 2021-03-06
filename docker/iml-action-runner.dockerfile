FROM rust-iml-base as builder
FROM imlteam/rust-service-base:6.1.0-dev

COPY --from=builder /build/target/release/iml-action-runner /usr/local/bin
COPY docker/wait-for-dependencies.sh /usr/local/bin/

ENTRYPOINT [ "wait-for-dependencies.sh" ]
CMD ["iml-action-runner"]
