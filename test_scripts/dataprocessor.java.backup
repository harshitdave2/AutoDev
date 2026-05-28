package test_scripts;

public class DataProcessor {
    private String data;

    public void process() {
        // MINIMAL BUG: data is never initialized, leading to a NullPointerException
        int length = data.length();
        System.out.println("Data length is: " + length);
    }

    public static void main(String[] args) {
        DataProcessor processor = new DataProcessor();
        processor.process();
    }
}
