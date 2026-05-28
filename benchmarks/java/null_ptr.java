/*
 * benchmarks/java/null_ptr.java
 * Bug: NullPointerException — method called on null object reference
 */
public class null_ptr {

    static String findEmail(String[][] users, String username) {
        for (String[] user : users) {
            if (user[0].equals(username)) {
                return user[1];
            }
        }
        return null;  // BUG: returns null when not found
    }

    static String formatUser(String[][] users, String username) {
        String email = findEmail(users, username);
        // BUG: no null check before calling .toUpperCase()
        return username.toUpperCase() + " <" + email.toUpperCase() + ">";
    }

    public static void main(String[] args) {
        String[][] users = {
            {"alice", "alice@example.com"},
            {"bob", "bob@example.com"}
        };
        System.out.println(formatUser(users, "alice"));
        System.out.println(formatUser(users, "charlie"));  // NullPointerException
    }
}
