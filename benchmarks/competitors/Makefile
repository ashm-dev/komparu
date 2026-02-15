.PHONY: all clean

all: compare_go compare_rs

compare_go: compare.go
	go build -o compare_go compare.go

compare_rs: compare.rs
	rustc -O -o compare_rs compare.rs

clean:
	rm -f compare_go compare_rs
