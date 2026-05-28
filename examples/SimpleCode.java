package examples;
public class SimpleCode {

     // Calculate square of a number 
    static int square(int n) {
        return n * n; // fixed the error here by changing '+' to '*'
     }

     // Check if a number is even 
    static boolean isEven(int n) {
        if (n % 2 == 0)
            return true;
        else
            return false;
    }

     // Calculate sum of array 
    static int sumArray(int[] arr) {
        int sum = 0;
        for (int i = 0; i < arr.length; i++) {
            sum += arr[i];
        }
        return sum;
    }

     public static void main(String[] args) {

         // Test square
        System.out.println("Square of 5: " + square(5));
        
         // Test isEven
        System.out.println("Is 4 even? " + isEven(4));
        System.out.println("Is 7 even? " + isEven(7));
        
         // Test sumArray
        int[] nums = { 1, 2, 3, 4, 5 };
        System.out.println("Sum: " + sumArray(nums));
        
     }
}