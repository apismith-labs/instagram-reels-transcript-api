// Command batch_csv is retained only as a safe migration notice.
// The former experimental implementation could repeat billable Run creation.
package main

import (
	"errors"
	"fmt"
	"os"
)

var errBatchRetired = errors.New("the Go CSV Batch example has been retired; it does not create Actor Runs")

func runBatch() error { return errBatchRetired }

func main() {
	if err := runBatch(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}
