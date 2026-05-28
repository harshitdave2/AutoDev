/*
 * benchmarks/java/type_cast.java
 * Bug: ClassCastException — incorrect type cast in generic collection
 */
import java.util.ArrayList;
import java.util.List;

public class type_cast {

    @SuppressWarnings("unchecked")
    static List<Integer> doubleAll(List<?> values) {
        List<Integer> result = new ArrayList<>();
        for (Object val : values) {
            // BUG: casts to Integer without checking — fails for non-Integer types
            Integer num = (Integer) val;
            result.add(num * 2);
        }
        return result;
    }

    public static void main(String[] args) {
        List<Object> mixed = new ArrayList<>();
        mixed.add(1);
        mixed.add(2);
        mixed.add("three");  // String in integer list — will cause ClassCastException
        mixed.add(4);

        List<Integer> doubled = doubleAll(mixed);
        System.out.println("Doubled: " + doubled);
    }
}
