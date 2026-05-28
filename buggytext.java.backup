import java.util.List;
import java.util.ArrayList;

public class BuggyTest {

    // ----------------------------------------
    // Feature 1: Calculate Average Score
    // BUG: ArithmeticException (/ by zero) when scores list is empty
    // ----------------------------------------
    public static int calculateAverage(List<Integer> scores) {
        int total = 0;
        for (int score : scores) {
            total += score;
        }
        // Java will throw ArithmeticException here if scores.size() is 0
        return total / scores.size(); 
    }

    // ----------------------------------------
    // Feature 2: Get User Score by Index
    // BUG: IndexOutOfBoundsException
    // ----------------------------------------
    public static int getScoreByIndex(List<Integer> scores, int index) {
        // Accessing an invalid index without checking bounds
        return scores.get(index);
    }

    // ----------------------------------------
    // Feature 3: Format User Report
    // BUG: NullPointerException
    // ----------------------------------------
    public static void printUserReport(String username, List<Integer> scores) {
        // Calling a method (.toUpperCase()) on a null object causes a NullPointerException
        System.out.print("User: " + username.toUpperCase() + " | ");
        
        int avg = calculateAverage(scores);
        System.out.println("Avg: " + avg);
    }

    // ----------------------------------------
    // Feature 4: Trigger Execution
    // ----------------------------------------
    public static void main(String[] args) {
        System.out.println("--- Starting AutoDev Java Test System ---");

        // Test 1: Empty scores will trigger ArithmeticException (/ by zero)
        List<Integer> emptyScores = new ArrayList<>();
        printUserReport("Alice", emptyScores);

        // Test 2: Out of bounds will trigger IndexOutOfBoundsException
        List<Integer> validScores = List.of(85, 90, 95);
        int badScore = getScoreByIndex(validScores, 10); // Index 10 doesn't exist
        System.out.println("Bad Score Retrieval: " + badScore);

        // Test 3: Passing null will trigger NullPointerException
        printUserReport(null, validScores);
    }
}