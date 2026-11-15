public class index_oob {
    static int[] computeCumulativeSum(int[] arr) {
        int[] cumSum = new int[arr.length];
        cumSum[0] = arr[0];
        for (int i = 1; i < arr.length; i++) {
            cumSum[i] = cumSum[i - 1] + arr[i];
        }
        return cumSum;
    }

    public static void main(String[] args) {
        int[] data = {1, 2, 3, 4, 5};
        int[] cumulative = computeCumulativeSum(data);
        System.out.print("Cumulative sum: ");
        for (int value : cumulative) System.out.print(value + " ");
        System.out.println();
    }
}
